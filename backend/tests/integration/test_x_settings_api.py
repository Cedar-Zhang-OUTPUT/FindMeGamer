from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.models.settings import ServiceSecret
from app.core.database import get_session
from app.core.rate_limit import FixedWindowRateLimiter
from app.integrations.connection_probe import ProductionConnectionProbe
from app.main import create_app
import app.main as main_module


PATH = "/api/v1/settings/connections/x"


@pytest.mark.parametrize("method", ["get", "put", "post"])
def test_x_settings_requires_workspace_auth(client, method):
    kwargs = {"json": {"secret": "fixture-x-bearer"}} if method == "put" else {}
    assert getattr(client, method)(PATH, **kwargs).status_code == 401


def test_x_secret_encrypted_replace_resets_test_and_never_returns_secret(
    auth_client, session, connection_probe
):
    missing = auth_client.get(PATH)
    assert missing.status_code == 200
    assert missing.json() == {
        "configured": False,
        "last_test_status": None,
        "last_tested_at": None,
    }
    first_secret = "fixture-x-bearer-first"
    saved = auth_client.put(PATH, json={"secret": first_secret})
    assert saved.status_code == 200
    connection_probe.expected = ("x", first_secret)
    tested = auth_client.post(PATH)
    assert tested.status_code == 200
    assert tested.json()["last_test_status"] == "success"
    session.expire_all()
    row = session.scalar(select(ServiceSecret).where(ServiceSecret.service == "x"))
    assert row is not None
    first_id, first_ciphertext = row.id, row.ciphertext
    assert first_secret.encode() not in row.ciphertext
    assert first_secret.encode() not in row.nonce
    replacement = "fixture-x-bearer-replacement"
    replaced = auth_client.put(PATH, json={"secret": replacement})
    assert replaced.json() == {
        "configured": True,
        "last_test_status": None,
        "last_tested_at": None,
    }
    session.expire_all()
    rows = session.scalars(
        select(ServiceSecret).where(ServiceSecret.service == "x")
    ).all()
    assert len(rows) == 1
    assert rows[0].id == first_id
    assert rows[0].ciphertext != first_ciphertext
    assert replacement.encode() not in rows[0].ciphertext
    connection_probe.expected = ("x", replacement)
    connection_probe.result = False
    rejected = auth_client.post(PATH)
    assert rejected.json()["last_test_status"] == "failure"
    assert rejected.json()["configured"] is True
    reread = auth_client.get(PATH)
    assert reread.json()["configured"] is True
    for response in [missing, saved, tested, replaced, rejected, reread]:
        assert first_secret not in response.text
        assert replacement not in response.text
        assert set(response.json()) == {
            "configured",
            "last_test_status",
            "last_tested_at",
        }


def test_app_wires_x_server_origin_to_real_probe(
    monkeypatch, session, workspace_access_key, rate_limit_counter, smtp_rate_limiter
):
    configured = main_module.get_settings().model_copy(
        update={"x_api_base_url": "http://127.0.0.1:9099/2"}
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: configured)
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"data": {"project_usage": 3}})

    @contextmanager
    def external_client(_self):
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            yield client

    monkeypatch.setattr(ProductionConnectionProbe, "_client", external_client)
    app = create_app(
        rate_limiter=FixedWindowRateLimiter(
            counter=rate_limit_counter, limit=100, window_seconds=60
        ),
        smtp_rate_limiter=smtp_rate_limiter,
    )

    def db_session():
        yield session

    app.dependency_overrides[get_session] = db_session
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {workspace_access_key}"
        assert (
            client.put(PATH, json={"secret": "fixture-x-app-bearer"}).status_code == 200
        )
        assert seen == []  # Saving never contacts a provider.
        response = client.post(PATH)
        assert response.status_code == 200
        assert response.json()["last_test_status"] == "success"
        assert "fixture-x-app-bearer" not in response.text
    assert len(seen) == 1
    assert seen[0].url == "http://127.0.0.1:9099/2/usage/tweets?days=1"
    assert seen[0].headers["authorization"] == "Bearer fixture-x-app-bearer"
