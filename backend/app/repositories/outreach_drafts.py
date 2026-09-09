"""Durable composition membership and explicitly refreshed personalization drafts."""

from sqlalchemy import select
from app.api.routes.activity import _get, _error
from app.db.models.activity_outreach import RecipientBatch, RecipientSnapshot
from app.db.models.discovery import Activity
from app.db.models.outreach_drafts import (
    OutreachComposition,
    OutreachDraft,
    OutreachTemplateVersion,
)
from app.discovery.evaluation_snapshot import digest
from app.outreach.draft_inputs import current_input, generation_ready
from app.outreach.locked_templates import render_locked
from app.schemas.outreach_drafts import DraftView, CompositionView
from app.core.idempotency import utc_now


def template_for(session, draft):
    composition = _get(session, OutreachComposition, draft.composition_id)
    return _get(session, OutreachTemplateVersion, composition.template_version_id)


def draft_view(session, draft):
    template = template_for(session, draft)
    live = current_input(session, draft.recipient_snapshot_id, template)
    token = digest(live)
    rendered = (
        render_locked(
            template.subject,
            template.fixed_fragments,
            draft.values,
            template.fixed_hash,
        )
        if draft.values
        else None
    )
    return DraftView(
        id=draft.id,
        composition_id=draft.composition_id,
        recipient_snapshot_id=draft.recipient_snapshot_id,
        selection_id=draft.input_data["selection_id"],
        input_order=draft.input_order,
        revision=draft.revision,
        context_token=token,
        source_changed=token != draft.input_fingerprint,
        status="failed" if expired(draft) else draft.status,
        error_code="draft_outcome_unknown" if expired(draft) else draft.error_code,
        input=draft.input_data,
        values=draft.values,
        missing_fields=live["missing_fields"],
        slot_sources=draft.input_data["slot_sources"],
        rendered=rendered,
        sender_facts_valid=facts_valid(draft, token),
        sender_facts=draft.sender_facts,
    ).model_dump(mode="json")


def composition_view(session, row):
    drafts = session.scalars(
        select(OutreachDraft)
        .where(OutreachDraft.composition_id == row.id)
        .order_by(OutreachDraft.input_order, OutreachDraft.id)
    ).all()
    return CompositionView(
        id=row.id,
        activity_id=row.activity_id,
        recipient_batch_id=row.recipient_batch_id,
        template_version_id=row.template_version_id,
        created_at=row.created_at,
        recipient_count=len(drafts),
        drafts=[draft_view(session, draft) for draft in drafts],
    ).model_dump(mode="json")


def create_composition(session, activity_id, value):
    request_fingerprint = digest(
        {"activity_id": str(activity_id), "request": value.model_dump(mode="json")}
    )
    old = session.scalar(
        select(OutreachComposition).where(
            OutreachComposition.request_id == value.request_id
        )
    )
    if old:
        if old.request_hash != request_fingerprint:
            raise _error(
                409,
                "composition_request_conflict",
                "This request already belongs to another composition.",
            )
        return composition_view(session, old)
    activity = _get(session, Activity, activity_id)
    batch = _get(session, RecipientBatch, value.recipient_batch_id)
    template = _get(session, OutreachTemplateVersion, value.template_version_id)
    if batch.activity_id != activity_id or template.game_id != activity.game_id:
        raise _error(
            422,
            "composition_source_mismatch",
            "Choose a recipient batch and template for this Activity and game.",
        )
    from app.repositories.outreach_templates_v2 import game_builtin
    from app.db.models.profiles import GameProfile

    current_template = game_builtin(
        session, _get(session, GameProfile, activity.game_id)
    )
    if (
        template.source_metadata.get("kind") != "game_bound"
        or template.fixed_hash != current_template["fixed_hash"]
    ):
        raise _error(
            409,
            "template_context_changed",
            "Register the current game-bound template before creating a new composition.",
        )
    row = OutreachComposition(
        activity_id=activity_id,
        recipient_batch_id=batch.id,
        template_version_id=template.id,
        request_id=value.request_id,
        request_hash=request_fingerprint,
    )
    session.add(row)
    session.flush()
    recipients = session.scalars(
        select(RecipientSnapshot)
        .where(RecipientSnapshot.batch_id == batch.id)
        .order_by(RecipientSnapshot.input_order, RecipientSnapshot.id)
    ).all()
    for recipient in recipients:
        data = current_input(session, recipient.id, template)
        session.add(
            OutreachDraft(
                composition_id=row.id,
                recipient_snapshot_id=recipient.id,
                input_order=recipient.input_order,
                input_data=data,
                input_fingerprint=digest(data),
                status="pending" if generation_ready(data) else "needs_repair",
            )
        )
    session.flush()
    return composition_view(session, row)


def check_context(session, row, value, *, refreshing=False):
    live = current_input(session, row.recipient_snapshot_id, template_for(session, row))
    token = digest(live)
    if (
        row.revision != value.expected_revision
        or token != value.context_token
        or (not refreshing and token != row.input_fingerprint)
    ):
        raise _error(
            409,
            "draft_context_changed",
            "Read the current draft and explicitly refresh changed source information.",
        )
    return live


def validate_bound_values(data, values):
    if not generation_ready(data):
        raise _error(
            422,
            "draft_sources_missing",
            "Record and confirm the required source information first.",
        )
    for key, source in (
        ("firstName", "public_name"),
        ("channelName", "channel_name"),
        ("reference", "reference"),
    ):
        if values[key] != data[source]:
            raise _error(
                422,
                "draft_value_not_bound",
                "Names and referenced work must match the chosen source records.",
            )


def clear_confirmation(row):
    row.sender_facts = {}
    row.lease_token = None
    row.lease_expires_at = None
    row.error_code = None
    row.revision += 1


def edit_draft(session, row, value):
    check_context(session, row, value)
    values = value.values.model_dump()
    validate_bound_values(row.input_data, values)
    template = template_for(session, row)
    render_locked(
        template.subject, template.fixed_fragments, values, template.fixed_hash
    )
    clear_confirmation(row)
    row.values = values
    row.status = "succeeded"
    session.flush()
    return draft_view(session, row)


def refresh_draft(session, row, value):
    data = check_context(session, row, value, refreshing=True)
    clear_confirmation(row)
    row.input_data, row.input_fingerprint = data, digest(data)
    row.values = None
    row.status = "pending" if generation_ready(data) else "needs_repair"
    session.flush()
    return draft_view(session, row)


def retry_draft(session, row, value):
    check_context(session, row, value)
    if row.status != "failed" and not expired(row):
        raise _error(
            409, "draft_retry_not_failed", "Only failed drafts may be retried."
        )
    clear_confirmation(row)
    row.status = "pending" if generation_ready(row.input_data) else "needs_repair"
    row.values = None
    session.flush()
    return draft_view(session, row)


def expired(row):
    return (
        row.status == "running"
        and row.lease_expires_at is not None
        and row.lease_expires_at <= utc_now()
    )


def fact_fingerprint(row):
    return digest(
        {"revision": row.revision, "values": row.values, "input": row.input_fingerprint}
    )


def facts_valid(row, live_token):
    return bool(
        row.values
        and row.status == "succeeded"
        and live_token == row.input_fingerprint
        and row.input_data["sender"].get("username")
        and all(
            row.sender_facts.get(key) is True
            for key in ("following", "enjoyed", "liked")
        )
        and row.sender_facts.get("fingerprint") == fact_fingerprint(row)
    )


def confirm_sender_facts(session, composition_id, value):
    composition = _get(session, OutreachComposition, composition_id)
    chosen = []
    for member in value.members:
        row = session.scalar(
            select(OutreachDraft)
            .where(OutreachDraft.id == member.draft_id)
            .with_for_update()
        )
        if row is None or row.composition_id != composition.id:
            raise _error(
                422,
                "draft_composition_mismatch",
                "Confirm only drafts from this composition.",
            )
        check_context(session, row, member)
        if not row.values or row.status != "succeeded":
            raise _error(
                422,
                "draft_not_complete",
                "Review completed personalization before confirming sender facts.",
            )
        chosen.append(row)
    for row in chosen:
        row.revision += 1
        row.sender_facts = {
            key: getattr(value, key) for key in ("following", "enjoyed", "liked")
        } | {
            "at": utc_now().isoformat(),
            "fingerprint": fact_fingerprint(row),
        }
    session.flush()
    return composition_view(session, composition)
