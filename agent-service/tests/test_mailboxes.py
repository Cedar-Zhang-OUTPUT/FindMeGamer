import json
from importlib import import_module

import pytest
from fastapi.testclient import TestClient

from fmg_agent.config import Settings
from fmg_agent.errors import ApiError


def registry(tmp_path, entries, **overrides):
    path = tmp_path / "mailboxes.json"
    path.write_text(json.dumps({"mailboxes": entries}))
    path.chmod(0o600)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'db.sqlite'}",
        mailboxes_file=path,
        **overrides,
    )
    return import_module("fmg_agent.mailboxes").MailboxRegistry.load(settings)


def profile(identity="alpha", **kwargs):
    return {
        "id": identity,
        "smtp_from": f"{identity}@example.com",
        "smtp_host": f"{identity}.example.com",
        "smtp_username": f"{identity}@example.com",
        "allowed_templates": ["game-outreach"],
        **kwargs,
    }


def test_registry_isolates_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv("FMG_AGENT_SMTP_PASSWORD", "environment-secret")
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    loaded = registry(
        tmp_path,
        [
            profile(
                smtp_password="first-secret",
                imap_host="imap.first",
                imap_password="imap-secret",
                microsoft_token_store=str(first),
            ),
            profile("beta", microsoft_token_store=str(second)),
        ],
        smtp_password="legacy-secret",
        imap_host="legacy.imap",
    )
    a, b = loaded.settings_for("alpha"), loaded.settings_for("beta")
    assert (
        a.smtp_host,
        a.smtp_password.get_secret_value(),
        a.microsoft_token_store,
    ) == ("alpha.example.com", "first-secret", first)
    assert (
        b.smtp_host,
        b.smtp_password.get_secret_value(),
        b.microsoft_token_store,
    ) == ("beta.example.com", "", second)
    assert b.imap_host == "" and b.imap_password.get_secret_value() == ""


@pytest.mark.parametrize(
    "case",
    [
        "address",
        "same-profile",
        "cross-profile",
        "id",
        "duplicate-id",
        "symlink",
        "relative",
    ],
)
def test_rejects_duplicate_identity_and_token_paths(tmp_path, case):
    a, b = profile(), profile("beta")
    token = tmp_path / "private-token.json"
    if case == "address":
        b["smtp_from"] = "ALPHA@example.com"
    elif case == "id":
        b["id"] = "BAD/secret"
    elif case == "duplicate-id":
        b["id"] = "alpha"
    elif case == "relative":
        a["microsoft_token_store"] = "private-token.json"
    else:
        a["microsoft_token_store"] = str(token)
        if case == "same-profile":
            a["microsoft_graph_token_store"] = str(token)
        elif case == "cross-profile":
            b["microsoft_graph_token_store"] = str(token)
        else:
            alias = tmp_path / "alias.json"
            alias.symlink_to(token)
            b["microsoft_token_store"] = str(alias)
    with pytest.raises(ApiError) as error:
        registry(tmp_path, [a, b])
    assert error.value.code == "mailbox_configuration_invalid"
    assert "private-token" not in str(error.value)
    assert "BAD/secret" not in str(error.value)


def test_public_mailboxes_redacts_secrets(tmp_path, caplog):
    from fmg_agent.app import create_app
    from fmg_agent.auth import issue_token
    from fmg_agent.db import Base

    loaded = registry(
        tmp_path,
        [
            profile(
                smtp_password="private-password",
                microsoft_token_store=str(tmp_path / "private-token"),
            ),
            {"id": "beta", "enabled": False},
        ],
    )
    app = create_app(loaded.settings_for("alpha"))
    Base.metadata.create_all(app.state.engine)
    with app.state.sessions() as session:
        token = issue_token(session, label="test", scopes=["email:send"])
        read = issue_token(session, label="read", scopes=["read"])
    with TestClient(app) as client:
        assert client.get("/v1/email/mailboxes").status_code == 401
        assert (
            client.get(
                "/v1/email/mailboxes", headers={"Authorization": f"Bearer {read.token}"}
            ).status_code
            == 403
        )
        response = client.get(
            "/v1/email/mailboxes", headers={"Authorization": f"Bearer {token.token}"}
        )
    assert response.status_code == 200
    assert response.json()["meta"]["mailboxes_version"] == 1
    assert response.json()["meta"]["request_id"]
    assert set(response.json()["data"][0]) == {
        "id",
        "from",
        "display_name",
        "enabled",
        "ready",
        "allowed_templates",
        "send_interval_seconds",
        "send_interval_choices_seconds",
    }
    assert response.json()["data"][0]["ready"] is True
    assert response.json()["data"][0]["send_interval_seconds"] == 8
    assert response.json()["data"][0]["send_interval_choices_seconds"] == [8, 9, 10]
    assert response.json()["data"][0]["from"] == "alpha@example.com"
    assert response.json()["data"][1]["enabled"] is False
    assert response.json()["data"][1]["ready"] is False
    for secret in ("private-password", str(tmp_path / "private-token")):
        assert secret not in response.text + caplog.text + repr(
            loaded.select("alpha", allow_legacy=False)
        )


def test_multi_mailbox_requires_selection(tmp_path):
    loaded = registry(tmp_path, [profile(), {"id": "beta", "enabled": False}])
    with pytest.raises(ApiError) as error:
        loaded.select(None, allow_legacy=True)
    assert error.value.code == "mailbox_selection_required"
    for identity, code in [
        ("missing", "mailbox_not_found"),
        ("beta", "mailbox_disabled"),
    ]:
        with pytest.raises(ApiError) as error:
            loaded.select(identity, allow_legacy=False)
        assert error.value.code == code
    legacy = import_module("fmg_agent.mailboxes").MailboxRegistry.load(
        Settings(database_url=f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    )
    assert legacy.select(None, allow_legacy=True).id == "ontologyplay"
    with pytest.raises(ApiError):
        legacy.select(None, allow_legacy=False)


@pytest.mark.parametrize(
    "contents,mode",
    [
        ("not json private-password", 0o600),
        ('{"mailboxes": []}', 0o600),
        ("{}", 0o600),
        (json.dumps({'mailboxes': [profile(smtp_password='private-password')]}), 0o644),
    ],
)
def test_invalid_registry_rejected_at_startup(tmp_path, contents, mode):
    from fmg_agent.app import create_app

    path = tmp_path / "mailboxes.json"
    path.write_text(contents)
    path.chmod(mode)
    with pytest.raises(ApiError) as error:
        create_app(
            Settings(
                database_url=f"sqlite:///{tmp_path / 'db.sqlite'}", mailboxes_file=path
            )
        )
    assert error.value.code == "mailbox_configuration_invalid"
    assert "private-password" not in str(error.value)


def test_oauth_readiness_is_read_only_and_checks_identity(tmp_path, monkeypatch):
    from fmg_agent.email import microsoft

    path = tmp_path / "token.json"
    path.write_text(
        json.dumps(
            {
                "client_id": "00000000-0000-0000-0000-000000000001",
                "mailbox": "other@example.com",
                "refresh_token": "private-refresh",
            }
        )
    )
    path.chmod(0o600)
    before = path.read_bytes()
    monkeypatch.setattr(
        microsoft, "access_token", lambda *a, **k: pytest.fail("OAuth refreshed")
    )
    loaded = registry(
        tmp_path,
        [
            profile(
                smtp_auth="microsoft_oauth",
                microsoft_client_id="00000000-0000-0000-0000-000000000001",
                microsoft_token_store=str(path),
            )
        ],
    )
    assert loaded.public_entries()[0]["ready"] is False
    assert path.read_bytes() == before
    assert not (tmp_path / "token.json.lock").exists()
    data = json.loads(path.read_text())
    data["mailbox"] = "alpha@example.com"
    path.write_text(json.dumps(data))
    assert loaded.public_entries()[0]["ready"] is True
    assert not (tmp_path / "token.json.lock").exists()
