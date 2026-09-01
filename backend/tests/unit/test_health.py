from fastapi.testclient import TestClient

from app.main import create_app


def test_live_health_is_process_only() -> None:
    response = TestClient(create_app()).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_title_is_stable() -> None:
    assert create_app().title == "Find Me Gamer API"
