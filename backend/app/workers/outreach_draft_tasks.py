"""One paid model attempt per claimed draft; retries require an explicit revision."""

from datetime import timedelta
from uuid import UUID, uuid4
from sqlalchemy import select
from app.core.config import get_settings
from app.core.crypto import EncryptedValue, SecretCipher
from app.core.database import session_scope
from app.core.idempotency import utc_now
from app.db.models.outreach_drafts import OutreachDraft
from app.discovery.evaluation_snapshot import digest
from app.integrations.errors import (
    IntegrationError,
    InvalidModelOutput,
    TransientIntegrationError,
)
from app.outreach.draft_inputs import current_input, generation_ready
from app.repositories.outreach_drafts import (
    template_for,
    validate_bound_values,
    expired,
)
from app.repositories.settings import SettingsRepository
from app.schemas.outreach_drafts import SlotValues
from app.workers.celery_app import celery_app


class DraftConfigurationMissing(Exception):
    pass


def production_execute(data):
    from app.integrations.deepseek import DeepSeekGateway
    from app.outreach.draft_ai import DraftAI

    with session_scope() as session:
        secret = SettingsRepository(session).get_connection("deepseek")
        if secret is None:
            raise DraftConfigurationMissing()
        encrypted = EncryptedValue(ciphertext=secret.ciphertext, nonce=secret.nonce)
    try:
        credential = SecretCipher.from_file(get_settings().master_key_file).decrypt(
            encrypted
        )
    except Exception:
        raise DraftConfigurationMissing() from None
    with DeepSeekGateway(
        api_key=credential, base_url=get_settings().deepseek_api_base_url
    ) as gateway:
        return DraftAI(gateway).generate(data)


def error_code(error):
    if isinstance(error, DraftConfigurationMissing):
        return "draft_configuration_missing"
    if isinstance(error, InvalidModelOutput) or isinstance(error, ValueError):
        return "draft_model_output_invalid"
    if isinstance(error, TransientIntegrationError):
        return "draft_model_unavailable"
    if isinstance(error, IntegrationError):
        return "draft_model_rejected"
    return "draft_failed"


def lock_draft(session, identity):
    return session.scalar(
        select(OutreachDraft)
        .where(OutreachDraft.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def run_draft(identity, *, session_factory=session_scope, execute=production_execute):
    with session_factory() as session:
        row = lock_draft(session, identity)
        if row is None:
            return
        if (
            row.status == "running"
            and row.lease_expires_at
            and row.lease_expires_at <= utc_now()
        ):
            row.status, row.error_code, row.lease_token = (
                "failed",
                "draft_outcome_unknown",
                None,
            )
            return
        if row.status != "pending":
            return
        live = current_input(
            session, row.recipient_snapshot_id, template_for(session, row)
        )
        if digest(live) != row.input_fingerprint or not generation_ready(live):
            row.status, row.error_code = "needs_repair", "draft_sources_changed"
            return
        token, revision = uuid4(), row.revision
        row.status, row.lease_token = "running", token
        row.lease_expires_at = utc_now() + timedelta(seconds=300)
        row.attempts += 1
        data = row.input_data
    values, failure = None, None
    try:
        result = execute(data)
        values = SlotValues.model_validate(result).model_dump()
        validate_bound_values(data, values)
    except Exception as error:
        failure = error_code(error)
    with session_factory() as session:
        row = lock_draft(session, identity)
        if (
            row is None
            or row.status != "running"
            or row.lease_token != token
            or row.revision != revision
        ):
            return
        if expired(row):
            failure = "draft_outcome_unknown"
        row.lease_token, row.lease_expires_at = None, None
        row.error_code = failure
        row.status = "failed" if failure else "succeeded"
        row.values = None if failure else values
        row.sender_facts = {}
        row.revision += 1


class CeleryDraftDispatcher:
    def dispatch(self, identity):
        celery_app.send_task(
            "find_me_gamer.outreach.generate_draft", args=[str(identity)]
        )


@celery_app.task(name="find_me_gamer.outreach.generate_draft")
def generate_draft(identity):
    run_draft(UUID(identity))
