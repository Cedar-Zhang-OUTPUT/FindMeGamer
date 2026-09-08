import pytest
from sqlalchemy import select

from app.db.models.settings import ServiceSecret


def test_defaults_separate_policy_capability_and_credentials(auth_client, session):
    response = auth_client.get("/api/v1/settings/collection")
    assert response.status_code == 200
    rows = {item["platform"]: item for item in response.json()["items"]}
    assert list(rows) == ["youtube", "x", "twitch", "instagram"]
    assert rows["youtube"] == {
        "platform": "youtube",
        "enabled": True,
        "implemented": True,
        "credentials_configured": False,
        "availability": "missing_connection",
    }
    assert rows["instagram"]["enabled"] is False
    assert rows["instagram"]["implemented"] is False
    assert rows["instagram"]["availability"] == "disabled"

    auth_client.put("/api/v1/settings/connections/x", json={"secret": "fixture-x"})
    secret = session.scalar(select(ServiceSecret).where(ServiceSecret.service == "x"))
    encrypted = bytes(secret.ciphertext)
    saved = auth_client.put("/api/v1/settings/collection/x", json={"enabled": False})
    assert saved.status_code == 200
    session.expire_all()
    assert bytes(session.get(ServiceSecret, secret.id).ciphertext) == encrypted
    rows = {item["platform"]: item for item in saved.json()["items"]}
    assert rows["x"]["availability"] == "disabled"
    assert rows["x"]["credentials_configured"] is True
    assert rows["youtube"]["enabled"] is True
    enabled = auth_client.put("/api/v1/settings/collection/x", json={"enabled": True})
    rows = {item["platform"]: item for item in enabled.json()["items"]}
    assert rows["x"]["availability"] == "configured_unverified"
    assert auth_client.get("/api/v1/settings/reanalysis").json() == {
        "creator_interval_days": 14,
        "game_interval_days": 30,
    }
    assert "fixture-x" not in enabled.text


def test_turning_on_preset_does_not_implement_provider(auth_client):
    saved = auth_client.put(
        "/api/v1/settings/collection/instagram", json={"enabled": True}
    )
    assert saved.status_code == 200
    reread = auth_client.get("/api/v1/settings/collection")
    assert reread.json() == saved.json()
    row = next(
        item for item in saved.json()["items"] if item["platform"] == "instagram"
    )
    assert row == {
        "platform": "instagram",
        "enabled": True,
        "implemented": False,
        "credentials_configured": False,
        "availability": "not_implemented",
    }


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/v1/settings/collection", None),
        ("put", "/api/v1/settings/collection/youtube", {"enabled": False}),
    ],
)
def test_collection_settings_requires_auth(client, method, path, body):
    response = getattr(client, method)(path, **({"json": body} if body else {}))
    assert response.status_code == 401


def test_collection_settings_rejects_unknown_platform_and_coerced_boolean(auth_client):
    assert (
        auth_client.put(
            "/api/v1/settings/collection/unknown", json={"enabled": True}
        ).status_code
        == 404
    )
    assert (
        auth_client.put(
            "/api/v1/settings/collection/x", json={"enabled": "false"}
        ).status_code
        == 422
    )
