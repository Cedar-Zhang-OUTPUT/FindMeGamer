from app.core import database


def test_database_session_dependency_is_available() -> None:
    assert callable(getattr(database, "get_session", None))
