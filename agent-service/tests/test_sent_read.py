import imaplib
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient

from fmg_agent.config import Settings
from fmg_agent.errors import ApiError
from fmg_agent.email.sent import read_sent, _identity, BODY_LIMIT


def config(**kwargs):
    return Settings(
        database_url="sqlite:////tmp/fmg-sent-unused-test.sqlite",
        smtp_from="sender@example.com",
        imap_username="sender@example.com",
        imap_password="private-secret",
        imap_host="imap.example.com",
        **kwargs,
    )


class FakeIMAP:
    def __init__(self, messages=None, validity=7, uidnext=42):
        self.messages = messages or {}
        self.validity, self.uidnext = validity, uidnext
        self.calls = []

    def login(self, username, password):
        self.calls.append(("login", username))
        assert password == "private-secret"

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        assert readonly
        return "OK", [b"1"]

    def response(self, name):
        return name, [
            str(self.validity if name == "UIDVALIDITY" else self.uidnext).encode()
        ]

    def uid(self, verb, target, query):
        self.calls.append((verb, target, query))
        assert verb == "FETCH" and "BODY.PEEK[" in query
        lo, hi = (
            map(int, target.split(":")) if ":" in target else (int(target), int(target))
        )
        cap = 4096 if "HEADER" in query else BODY_LIMIT
        return "OK", [
            (f"1 (UID {uid} RFC822.SIZE {len(raw)}".encode(), raw[:cap])
            for uid, raw in self.messages.items()
            if lo <= uid <= hi
        ]

    def logout(self):
        self.calls.append(("logout",))


def message():
    msg = EmailMessage()
    msg["Subject"] = "测试 sent"
    msg["To"] = "reader@example.com"
    msg["Message-ID"] = "<one@example.com>"
    msg.set_content("plain body")
    msg.add_alternative("<p>HTML body</p>", subtype="html")
    msg.add_attachment(
        b"do not expose",
        maintype="application",
        subtype="octet-stream",
        filename="secret.txt",
    )
    return msg.as_bytes()


def read(fake, **kwargs):
    return read_sent(config(), "liminal", connect=lambda *a, **k: fake, **kwargs)


def test_list_readonly_descending_and_sparse_pagination():
    fake = FakeIMAP({40: message(), 41: message(), 1: message()})
    page = read(fake, limit=20)
    assert [m["uid"] for m in page["messages"]] == [41, 40]
    assert page["messages"][0]["headers"]["Subject"] == "测试 sent"
    assert "text" not in page["messages"][0]
    second = read(fake, cursor=page["next_cursor"], limit=20)
    assert second["messages"] == [] and second["next_cursor"]
    last = read(fake, cursor=second["next_cursor"], limit=20)
    assert [m["uid"] for m in last["messages"]] == [1]
    assert last["next_cursor"] is None
    assert all(c[0] in {"login", "select", "FETCH", "logout"} for c in fake.calls)


def test_detail_body_and_attachment_exclusion():
    fake = FakeIMAP({41: message()})
    identity = read(fake)["messages"][0]["id"]
    msg = read(fake, message_id=identity)["message"]
    assert not msg["body_omitted"]
    assert msg["text"].strip() == "plain body"
    assert "HTML body" in msg["html"]
    assert "do not expose" not in str(msg)


def test_large_message_has_no_partial_body():
    fake = FakeIMAP({41: b"Subject: Large\r\n\r\n" + b"a" * (BODY_LIMIT + 1)})
    identity = read(fake)["messages"][0]["id"]
    msg = read(fake, message_id=identity)["message"]
    assert msg["body_omitted"] and msg["text"] is None


@pytest.mark.parametrize(
    "reference,code",
    [
        ("wrong:7:41", "sent_reference_invalid"),
        ("{identity}:6:41", "sent_folder_changed"),
        ("{identity}:7:999", "sent_message_not_found"),
        ("{identity}:7:40", "sent_message_not_found"),
        ("{identity}:7:1 UID STORE", "sent_reference_invalid"),
    ],
)
def test_invalid_stale_or_missing_reference(reference, code):
    fake = FakeIMAP({41: message()})
    with pytest.raises(ApiError) as caught:
        read(
            fake,
            message_id=reference.format(
                identity=_identity(
                    "liminal", "Sent", "imap.example.com:993:sender@example.com"
                )
            ),
        )
    assert caught.value.code == code
    assert fake.calls[-1] == ("logout",)


def test_empty_folder_does_not_fetch_star_or_reverse_range():
    fake = FakeIMAP(uidnext=1)
    assert read(fake)["messages"] == []
    assert not any(c[0] == "FETCH" for c in fake.calls)


def test_auth_errors_sanitized_and_logout():
    fake = FakeIMAP()

    def fail(*args):
        raise imaplib.IMAP4.error("private-secret authentication failure")

    fake.login = fail
    with pytest.raises(ApiError) as caught:
        read(fake)
    assert caught.value.code == "sent_auth_failed"
    assert "private-secret" not in caught.value.message
    assert fake.calls[-1] == ("logout",)


def test_api_scope_mailbox_isolation_and_validation(tmp_path, monkeypatch):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.db import Base
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile
    from fmg_agent.email import sent

    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'db.sqlite'}"))
    Base.metadata.create_all(app.state.engine)
    app.state.mailboxes = MailboxRegistry(
        app.state.settings,
        [
            MailboxProfile(
                id="liminal", smtp_from="l@example.com", imap_host="l.example.com"
            ),
            MailboxProfile(
                id="second", smtp_from="s@example.com", imap_host="s.example.com"
            ),
            MailboxProfile(id="old", enabled=False),
        ],
        legacy=False,
    )
    calls = []

    def stub(settings, mailbox_id, **kwargs):
        calls.append((mailbox_id, settings.imap_host))
        return {"messages": [], "next_cursor": None}

    monkeypatch.setattr(sent, "read_sent", stub)
    with app.state.sessions() as session:
        sender = issue_token(session, label="send", scopes=["email:send"])
        reader = issue_token(session, label="read", scopes=["email:read"])
    with TestClient(app) as client:
        path = "/v1/email/sent?mailbox_id=liminal"
        assert client.get(path).status_code == 401
        assert (
            client.get(
                path, headers={"Authorization": f"Bearer {sender.token}"}
            ).status_code
            == 403
        )
        headers = {"Authorization": f"Bearer {reader.token}"}
        assert client.get("/v1/email/mailboxes", headers=headers).status_code == 200
        assert client.get(path, headers=headers).status_code == 200
        assert (
            client.get("/v1/email/sent?mailbox_id=second", headers=headers).status_code
            == 200
        )
        assert calls == [("liminal", "l.example.com"), ("second", "s.example.com")]
        for suffix, status in [("&limit=51", 422), ("&cursor=a&message_id=b", 422)]:
            assert client.get(path + suffix, headers=headers).status_code == status
        assert (
            client.get("/v1/email/sent?mailbox_id=old", headers=headers).status_code
            == 409
        )
        assert (
            client.get("/v1/email/sent?mailbox_id=missing", headers=headers).status_code
            == 404
        )
        assert len(calls) == 2


def test_network_and_fetch_failures_are_retryable_and_redacted():
    fake = FakeIMAP()

    def fail(*args):
        raise OSError("private-secret disconnected")

    fake.uid = fail
    with pytest.raises(ApiError) as caught:
        read(fake)
    assert caught.value.code == "sent_read_failed" and caught.value.retryable
    assert "private-secret" not in caught.value.message
    assert fake.calls[-1] == ("logout",)


def test_header_truncation_reported():
    fake = FakeIMAP({41: b"Subject: " + b"x" * 3000 + b"\r\n\r\n"})
    record = read(fake)["messages"][0]
    assert record["headers_truncated"]
    assert len(record["headers"]["Subject"]) == 2000


def test_same_mailbox_migrated_account_rejects_old_reference():
    fake = FakeIMAP({41: message()})
    identity = read(fake)["messages"][0]["id"]
    changed = config().model_copy(update={"imap_host": "new.example.com"})
    with pytest.raises(ApiError) as caught:
        read_sent(changed, "liminal", message_id=identity, connect=lambda *a, **k: fake)
    assert caught.value.code == "sent_reference_invalid"
