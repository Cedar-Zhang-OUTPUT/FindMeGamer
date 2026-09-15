"""Migrations deliberately cannot target the legacy product database."""

from alembic import context
from sqlalchemy.exc import SQLAlchemyError

from fmg_agent.config import Settings
from fmg_agent.db import Base, database


def run():
    try:
        settings = Settings()
    except ValueError:
        raise SystemExit("Set a valid isolated agent database configuration.") from None
    if context.is_offline_mode():
        context.configure(
            url=settings.database_url, target_metadata=Base.metadata, literal_binds=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine, _ = database(settings)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
    except SQLAlchemyError:
        raise SystemExit(
            "Migration failed; check isolated database connectivity and schema."
        ) from None
    finally:
        engine.dispose()


run()
