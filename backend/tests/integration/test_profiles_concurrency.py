from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from threading import Barrier, Lock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, event, select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.profiles import CreatorContact, CreatorProfile
from app.main import create_app


class AlwaysAllow:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


@dataclass
class IndependentProfilesHarness:
    first: TestClient
    second: TestClient
    creator_id: UUID
    engine: Engine


@pytest.fixture
def independent_profiles_harness(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> Iterator[IndependentProfilesHarness]:
    _reset_profiles(database_engine)
    with Session(database_engine) as database_session:
        creator = CreatorProfile(
            youtube_channel_id=f"concurrent-manual-{uuid4()}",
            canonical_url="https://youtube.com/channel/concurrent-manual",
            sort_name="Concurrent Manual",
        )
        database_session.add(creator)
        database_session.commit()
        creator_id = creator.id

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AlwaysAllow(),
        secret_cipher=SecretCipher(bytes(range(32))),
    )

    def independent_session() -> Iterator[Session]:
        with Session(database_engine) as database_session:
            try:
                yield database_session
                database_session.commit()
            except Exception:
                database_session.rollback()
                raise

    app.dependency_overrides[get_session] = independent_session
    authorization = {"Authorization": f"Bearer {workspace_access_key}"}
    try:
        with TestClient(app, headers=authorization) as first:
            with TestClient(app, headers=authorization) as second:
                yield IndependentProfilesHarness(
                    first=first,
                    second=second,
                    creator_id=creator_id,
                    engine=database_engine,
                )
    finally:
        app.dependency_overrides.clear()
        _reset_profiles(database_engine)


def test_concurrent_first_manual_updates_serialize_without_duplicate_or_lost_write(
    independent_profiles_harness: IndependentProfilesHarness,
) -> None:
    harness = independent_profiles_harness
    selects_ready = Barrier(2)
    seen_connections: set[int] = set()
    seen_lock = Lock()

    def synchronize_first_creator_reads(
        connection, cursor, statement, parameters, context, executemany
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if not normalized.startswith("select creator_profiles"):
            return
        connection_id = id(connection)
        with seen_lock:
            if connection_id in seen_connections:
                return
            seen_connections.add(connection_id)
        selects_ready.wait(timeout=5)

    event.listen(
        harness.engine, "before_cursor_execute", synchronize_first_creator_reads
    )
    try:
        requests = [
            (
                harness.first,
                {"contact_email": "first@example.com", "notes": "First write"},
            ),
            (
                harness.second,
                {"contact_email": "second@example.com", "notes": "Second write"},
            ),
        ]
        response_bodies = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(
                    client.patch,
                    f"/api/v1/profiles/creators/{harness.creator_id}/manual",
                    json=payload,
                ): payload
                for client, payload in requests
            }
            for future in as_completed(futures, timeout=10):
                response = future.result(timeout=5)
                assert response.status_code == 200
                response_bodies.append(response.json())
    finally:
        event.remove(
            harness.engine, "before_cursor_execute", synchronize_first_creator_reads
        )

    with Session(harness.engine) as database_session:
        active_manuals = database_session.scalars(
            select(CreatorContact).where(
                CreatorContact.creator_id == harness.creator_id,
                CreatorContact.is_manual.is_(True),
                CreatorContact.is_active.is_(True),
            )
        ).all()
        creator = database_session.get(CreatorProfile, harness.creator_id)

    final_detail = harness.first.get(
        f"/api/v1/profiles/creators/{harness.creator_id}"
    )
    expected_notes = {
        "first@example.com": "First write",
        "second@example.com": "Second write",
    }

    assert len(active_manuals) == 1
    assert creator is not None
    final_email = active_manuals[0].email
    assert creator.manual_notes == expected_notes[final_email]
    assert all(body["contact"]["source"] == "manual" for body in response_bodies)
    assert final_detail.json()["contact"]["email"] == final_email
    assert final_detail.json()["manual_notes"] == expected_notes[final_email]


def _reset_profiles(engine: Engine) -> None:
    with Session(engine) as database_session:
        database_session.execute(delete(CreatorContact))
        database_session.execute(delete(CreatorProfile))
        database_session.commit()
