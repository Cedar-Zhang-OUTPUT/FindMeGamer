from uuid import uuid4

from alembic import command
from sqlalchemy import text


def test_0013_upgrade_preserves_jobs_secrets_and_shared_settings(
    migrated_database, alembic_config, database_engine
):
    job_id, secret_id = uuid4(), uuid4()
    try:
        command.downgrade(alembic_config, "20260908_0013")
        with database_engine.begin() as conn:
            conn.execute(
                text(
                    """INSERT INTO analysis_jobs
                (id,target_type,canonical_target_id,canonical_url,mode,status,completed_units,total_units,retryable)
                VALUES (:id,'creator','UCfixture12','https://www.youtube.com/channel/UCfixture12','reanalyze','queued',0,0,false)"""
                ),
                {"id": job_id},
            )
            conn.execute(
                text(
                    """INSERT INTO service_secrets(id,service,ciphertext,nonce)
                VALUES (:id,'collection-migration-fixture',decode('010203','hex'),decode('040506','hex'))"""
                ),
                {"id": secret_id},
            )
            before_job = conn.scalar(
                text("SELECT to_jsonb(j) FROM analysis_jobs j WHERE id=:id"),
                {"id": job_id},
            )
            before_secret = conn.scalar(
                text("SELECT to_jsonb(s) FROM service_secrets s WHERE id=:id"),
                {"id": secret_id},
            )
            before_settings = conn.scalar(
                text("SELECT to_jsonb(s) FROM shared_settings s")
            )
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            assert (
                conn.scalar(
                    text(
                        "SELECT to_jsonb(j)-'collection_paused' FROM analysis_jobs j WHERE id=:id"
                    ),
                    {"id": job_id},
                )
                == before_job
            )
            assert (
                conn.scalar(
                    text("SELECT collection_paused FROM analysis_jobs WHERE id=:id"),
                    {"id": job_id},
                )
                is False
            )
            assert (
                conn.scalar(
                    text("SELECT to_jsonb(s) FROM service_secrets s WHERE id=:id"),
                    {"id": secret_id},
                )
                == before_secret
            )
            assert (
                conn.scalar(
                    text(
                        "SELECT to_jsonb(s)-'collection_enabled' FROM shared_settings s"
                    )
                )
                == before_settings
            )
            assert (
                conn.scalar(text("SELECT collection_enabled FROM shared_settings"))
                == {}
            )
    finally:
        command.upgrade(alembic_config, "head")
        with database_engine.begin() as conn:
            conn.execute(text("DELETE FROM analysis_jobs WHERE id=:id"), {"id": job_id})
            conn.execute(
                text("DELETE FROM service_secrets WHERE id=:id"), {"id": secret_id}
            )
