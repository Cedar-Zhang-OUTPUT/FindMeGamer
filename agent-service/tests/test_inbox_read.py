"""Mailbox-wide reads must not depend on monitored replies or change mail state."""

import imaplib

import pytest
from fastapi.testclient import TestClient

from fmg_agent.app import create_app
from fmg_agent.auth import issue_token
from fmg_agent.config import Settings
from fmg_agent.db import Base
from fmg_agent.mailboxes import MailboxProfile, MailboxRegistry
from test_sent_read import FakeIMAP, message


@pytest.fixture
def mailbox_api(tmp_path, monkeypatch):
    app = create_app(Settings(database_url=f"sqlite:///{tmp_path / 'db.sqlite'}"))
    Base.metadata.create_all(app.state.engine)
    app.state.mailboxes = MailboxRegistry(
        app.state.settings,
        [
            MailboxProfile(
                id=name,
                smtp_from=f"{name}@example.com",
                imap_username=f"{name}@example.com",
                imap_password="private-secret",
                imap_host="imap.example.com",
                imap_folder="INBOX",
            )
            for name in ("liminal", "second")
        ]
        + [MailboxProfile(id="old", enabled=False)],
        legacy=False,
    )
    fake = FakeIMAP({41: message(), 40: message(), 1: message()})
    monkeypatch.setattr(imaplib, "IMAP4_SSL", lambda *a, **k: fake)
    with app.state.sessions() as session:
        reader = issue_token(session, label="reader", scopes=["email:read"])
        sender = issue_token(session, label="sender", scopes=["email:send"])
    with TestClient(app) as client:
        yield client, {"Authorization": f"Bearer {reader.token}"}, sender, fake


@pytest.mark.parametrize("mailbox", ["liminal", "second"])
def test_inbox_lists_all_mail_and_reads_body_without_writes(mailbox_api, mailbox):
    client, headers, _, fake = mailbox_api
    path = f"/v1/email/inbox?mailbox_id={mailbox}"
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    page = response.json()["data"]
    assert page["folder"] == "INBOX" and page["mailbox_id"] == mailbox
    assert [m["uid"] for m in page["messages"]] == [41, 40]
    identity = page["messages"][0]["id"]
    detail = client.get(path + "&message_id=" + identity, headers=headers)
    assert detail.status_code == 200
    mail = detail.json()["data"]["message"]
    assert mail["text"].strip() == "plain body" and not mail["body_omitted"]
    assert "do not expose" not in str(mail)
    assert ("select", '"INBOX"', True) in fake.calls
    assert ("login", f"{mailbox}@example.com") in fake.calls
    assert all(c[0] in {"login", "select", "FETCH", "logout"} for c in fake.calls)
    middle = client.get(
        path + "&cursor=" + page["next_cursor"], headers=headers
    ).json()["data"]
    assert middle["messages"] == [] and middle["next_cursor"]
    last = client.get(
        path + "&cursor=" + middle["next_cursor"], headers=headers
    ).json()["data"]
    assert [m["uid"] for m in last["messages"]] == [1] and last["next_cursor"] is None


def test_inbox_requires_scope_and_enabled_mailbox(mailbox_api):
    client, headers, sender, fake = mailbox_api
    path = "/v1/email/inbox?mailbox_id=liminal"
    assert client.get(path).status_code == 401
    assert (
        client.get(
            path, headers={"Authorization": f"Bearer {sender.token}"}
        ).status_code
        == 403
    )
    for suffix, code in [("&limit=51", 422), ("&cursor=a&message_id=b", 422)]:
        assert client.get(path + suffix, headers=headers).status_code == code
    assert (
        client.get("/v1/email/inbox?mailbox_id=old", headers=headers).status_code == 409
    )
    assert (
        client.get("/v1/email/inbox?mailbox_id=missing", headers=headers).status_code
        == 404
    )
    assert fake.calls == []


def test_inbox_sent_and_mailboxes_have_separate_references(mailbox_api):
    client, headers, _, fake = mailbox_api

    def request(folder, mailbox="liminal", **params):
        return client.get(
            f"/v1/email/{folder}",
            params={"mailbox_id": mailbox, **params},
            headers=headers,
        )

    sent = request("sent").json()["data"]["messages"][0]["id"]
    inbox_response = request("inbox")
    assert inbox_response.status_code == 200
    inbox = inbox_response.json()["data"]["messages"][0]["id"]
    for folder, mailbox, ref in [
        ("inbox", "liminal", sent),
        ("sent", "liminal", inbox),
        ("inbox", "second", inbox),
    ]:
        result = request(folder, mailbox, message_id=ref)
        assert result.status_code == 422
        assert result.json()["error"]["code"] == f"{folder}_reference_invalid"
    fake.validity += 1
    result = request("inbox", message_id=inbox)
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "inbox_folder_changed"


def test_inbox_auth_errors_are_specific_and_redacted(mailbox_api):
    client, headers, _, fake = mailbox_api

    def fail(*args):
        raise imaplib.IMAP4.error("private-secret was rejected")

    fake.login = fail
    result = client.get("/v1/email/inbox?mailbox_id=liminal", headers=headers)
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "inbox_auth_failed"
    assert "private-secret" not in result.text
    assert fake.calls[-1] == ("logout",)


def test_inbox_empty_large_and_missing_messages(mailbox_api):
    from fmg_agent.email.folders import BODY_LIMIT

    client, headers, _, fake = mailbox_api
    path = "/v1/email/inbox?mailbox_id=liminal"
    fake.messages = {41: b"Subject: large\r\n\r\n" + b"x" * (BODY_LIMIT + 1)}
    identity = client.get(path, headers=headers).json()["data"]["messages"][0]["id"]
    result = client.get(path + "&message_id=" + identity, headers=headers).json()[
        "data"
    ]["message"]
    assert result["body_omitted"] and result["text"] is None and result["html"] is None
    fake.messages = {}
    result = client.get(path + "&message_id=" + identity, headers=headers)
    assert (
        result.status_code == 404
        and result.json()["error"]["code"] == "inbox_message_not_found"
    )
    fake.uidnext = 1
    fake.calls.clear()
    result = client.get(path, headers=headers).json()["data"]
    assert result["messages"] == [] and result["next_cursor"] is None
    assert not any(c[0] == "FETCH" for c in fake.calls)


def test_folder_read_concurrency_keeps_other_api_requests_available(mailbox_api):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Event
    from fmg_agent.email.folders import read_inbox
    from fmg_agent.email.sent import read_sent
    from fmg_agent.errors import ApiError
    from test_sent_read import config

    client, headers, _, fake = mailbox_api
    arrived, release = Barrier(3), Event()

    class SlowIMAP(FakeIMAP):
        def select(self, folder, readonly=False):
            arrived.wait(timeout=5)
            assert release.wait(5)
            return super().select(folder, readonly)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(reader, config(), "liminal", connect=lambda *a, **k: SlowIMAP())
            for reader in (read_inbox, read_sent)
        ]
        try:
            arrived.wait(timeout=5)
            result = client.get("/v1/email/inbox?mailbox_id=second", headers=headers)
            assert result.status_code == 503
            assert result.json()["error"]["code"] == "inbox_read_busy"
            assert result.json()["error"]["retry_after_seconds"] == 2
            assert fake.calls == []
            assert client.get("/v1/health").status_code == 200
        finally:
            release.set()
        for f in futures:
            assert f.result(timeout=5)["messages"] == []
    assert (
        client.get("/v1/email/inbox?mailbox_id=second", headers=headers).status_code
        == 200
    )


def test_inbox_connection_failure_releases_read_slot():
    from fmg_agent.email.folders import read_inbox
    from fmg_agent.errors import ApiError
    from test_sent_read import config

    def fail(*a, **k):
        raise OSError("private-secret connection lost")

    for _ in range(3):
        with pytest.raises(ApiError) as error:
            read_inbox(config(), "liminal", connect=fail)
        assert error.value.code == "inbox_read_failed" and error.value.retryable
        assert "private-secret" not in error.value.message
    assert (
        read_inbox(config(), "liminal", connect=lambda *a, **k: FakeIMAP())["messages"]
        == []
    )
