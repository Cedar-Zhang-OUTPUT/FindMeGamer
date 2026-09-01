from uuid import uuid4

from fastapi import Depends
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.db.models.idempotency import IdempotencyRecord


def test_client_commit_stays_inside_rollback_isolated_transaction(
    client, session: Session, database_engine: Engine
) -> None:
    key = f"client-transaction-{uuid4()}"

    def commit_record(database_session: Session = Depends(get_session)) -> dict[str, str]:
        database_session.add(
            IdempotencyRecord(
                key=key,
                request_hash="b" * 64,
                method="POST",
                path="/_test/commit",
                response_status=200,
                response_body={"status": "ok"},
            )
        )
        database_session.commit()
        return {"status": "ok"}

    client.app.add_api_route("/_test/commit", commit_record, methods=["POST"])

    assert client.post("/_test/commit").json() == {"status": "ok"}
    assert session.scalar(
        select(func.count())
        .select_from(IdempotencyRecord)
        .where(IdempotencyRecord.key == key)
    ) == 1
    with database_engine.connect() as connection:
        persisted_count = connection.scalar(
            select(func.count())
            .select_from(IdempotencyRecord)
            .where(IdempotencyRecord.key == key)
        )
    assert persisted_count == 0
