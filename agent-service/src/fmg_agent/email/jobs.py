"""Durable checkpoints and compare-and-set leases, without network side effects."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update, delete
from sqlalchemy.exc import IntegrityError

from ..errors import ApiError
from ..db import AccessToken
from .models import EmailJob


def utcnow():
    return datetime.now(timezone.utc)


def snapshot(row):
    return {
        key: getattr(row, key)
        for key in (
            "id",
            "token_id",
            "run_id",
            "input",
            "state",
            "checkpoints",
            "emails",
            "error",
            "created_at",
            "updated_at",
        )
    }


class JobStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def create(self, token_id, key, payload, run_id=None):
        with self.sessions() as session:
            row = EmailJob(
                token_id=token_id, idempotency_key=key, input=payload, run_id=run_id
            )
            session.add(row)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                row = session.scalar(
                    select(EmailJob).where(
                        EmailJob.token_id == token_id, EmailJob.idempotency_key == key
                    )
                )
                if row is None:
                    raise
                if row.input != payload:
                    raise ApiError(
                        409,
                        "idempotency_conflict",
                        "This key belongs to different input.",
                    ) from None
            return snapshot(row)

    def load(self, job_id, token_id=None):
        with self.sessions() as session:
            row = session.get(EmailJob, job_id)
            if row is None or (token_id is not None and row.token_id != token_id):
                raise ApiError(404, "job_not_found", "Email job was not found.")
            return snapshot(row)

    def retry(self, job_id, token_id):
        with self.sessions() as session:
            row = session.get(EmailJob, job_id)
            if row is None or row.token_id != token_id:
                raise ApiError(404, "job_not_found", "Email job was not found.")
            if row.state == "completed":
                raise ApiError(
                    409, "job_completed", "Completed jobs do not need retry."
                )
            if row.state == "failed":
                session.execute(
                    update(EmailJob)
                    .where(EmailJob.id == job_id, EmailJob.state == "failed")
                    .values(
                        state="queued",
                        error=None,
                        lease=None,
                        lease_until=None,
                        updated_at=utcnow(),
                    )
                )
                session.commit()
                session.refresh(row)
            return snapshot(row)

    def pending(self, limit=100):
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(EmailJob.id)
                    .where(EmailJob.state == "queued")
                    .order_by(EmailJob.created_at)
                    .limit(limit)
                )
            )

    def claim(self, job_id, now=None):
        now = now or utcnow()
        lease = str(uuid4())
        with self.sessions() as session:
            active = select(AccessToken.id).where(AccessToken.revoked_at.is_(None))
            session.execute(
                update(EmailJob)
                .where(
                    EmailJob.id == job_id,
                    EmailJob.state == "queued",
                    EmailJob.token_id.not_in(active),
                )
                .values(
                    state="failed",
                    error={"code": "access_revoked", "retryable": False},
                    updated_at=now,
                )
            )
            changed = session.execute(
                update(EmailJob)
                .where(
                    EmailJob.id == job_id,
                    EmailJob.state == "queued",
                    EmailJob.token_id.in_(active),
                )
                .values(
                    state="running",
                    lease=lease,
                    lease_until=now + timedelta(minutes=15),
                    updated_at=now,
                )
            ).rowcount
            session.commit()
        return lease if changed else None

    def cleanup(self, retention_days):
        with self.sessions() as session:
            changed = session.execute(
                delete(EmailJob).where(
                    EmailJob.state.in_(["completed", "failed"]),
                    EmailJob.updated_at < utcnow() - timedelta(days=retention_days),
                )
            ).rowcount
            session.commit()
            return changed

    def checkpoint(self, job_id, lease, stage, value):
        with self.sessions() as session:
            row = session.get(EmailJob, job_id)
            if row is None or row.state != "running" or row.lease != lease:
                return False
            values = dict(row.checkpoints)
            values[stage] = value
            changed = session.execute(
                update(EmailJob)
                .where(
                    EmailJob.id == job_id,
                    EmailJob.state == "running",
                    EmailJob.lease == lease,
                )
                .values(checkpoints=values, updated_at=utcnow())
            ).rowcount
            session.commit()
            return bool(changed)

    def _finish(self, job_id, lease, **values):
        with self.sessions() as session:
            changed = session.execute(
                update(EmailJob)
                .where(
                    EmailJob.id == job_id,
                    EmailJob.state == "running",
                    EmailJob.lease == lease,
                )
                .values(**values, lease=None, lease_until=None, updated_at=utcnow())
            ).rowcount
            session.commit()
            return bool(changed)

    def fail(self, job_id, lease, code, *, retryable):
        return self._finish(
            job_id, lease, state="failed", error={"code": code, "retryable": retryable}
        )

    def complete(self, job_id, lease, emails):
        return self._finish(job_id, lease, state="completed", emails=emails, error=None)

    def recover_expired(self):
        with self.sessions() as session:
            result = session.execute(
                update(EmailJob)
                .where(EmailJob.state == "running", EmailJob.lease_until < utcnow())
                .values(
                    state="failed",
                    lease=None,
                    lease_until=None,
                    error={"code": "execution_interrupted", "retryable": True},
                    updated_at=utcnow(),
                )
            )
            session.commit()
            return result.rowcount
