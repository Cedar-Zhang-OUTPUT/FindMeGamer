from fastapi.testclient import TestClient

from app.api.routes.health import ReadinessProbe
from app.main import create_app


def test_live_health_is_process_only() -> None:
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_title_is_stable() -> None:
    assert create_app().title == "Find Me Gamer API"


def test_ready_health_requires_postgresql_and_redis() -> None:
    readiness_probe = ReadinessProbe(
        database_check=lambda: True,
        redis_check=lambda: True,
    )

    response = TestClient(create_app(readiness_probe=readiness_probe)).get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_health_returns_service_unavailable_when_postgresql_fails() -> None:
    readiness_probe = ReadinessProbe(
        database_check=lambda: False,
        redis_check=lambda: True,
    )

    response = TestClient(create_app(readiness_probe=readiness_probe)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


def test_ready_health_returns_service_unavailable_when_redis_fails() -> None:
    readiness_probe = ReadinessProbe(
        database_check=lambda: True,
        redis_check=lambda: False,
    )

    response = TestClient(create_app(readiness_probe=readiness_probe)).get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
