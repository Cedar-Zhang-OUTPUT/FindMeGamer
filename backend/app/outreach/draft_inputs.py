"""Source-bound personalization inputs, separate from historical recipient snapshots."""

from sqlalchemy import select
from app.api.routes.activity import _get
from app.db.models.activity_outreach import ActivitySelection, RecipientSnapshot
from app.db.models.discovery import Activity
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.settings import SharedSettings
from app.repositories.activity_preparation import preparation
from app.repositories.creator_library import effective_fields
from app.repositories.library_v2 import game_detail


def current_input(session, recipient_id, template):
    recipient = _get(session, RecipientSnapshot, recipient_id)
    selection = _get(session, ActivitySelection, recipient.selection_id)
    prepared = preparation(session, selection)
    creator = _get(session, CreatorProfile, selection.creator_id)
    activity = _get(session, Activity, selection.activity_id)
    game = game_detail(_get(session, GameProfile, activity.game_id)).model_dump(
        mode="json"
    )
    fields = effective_fields(creator)
    works = prepared["works"]
    work = next(
        (
            w
            for w in works
            if w.get("source_url")
            and w.get("evidence_excerpt")
            and w.get("verification_notes")
        ),
        works[0] if works else {},
    )
    reference = work.get("content_title") or work.get("work_name")
    missing = []
    for key, condition in (
        ("not_selected", not prepared["active"]),
        ("identity_changed", prepared["identity_changed"]),
        ("public_name_unconfirmed", not prepared["public_name_confirmed"]),
        ("channel_name_missing", not prepared["name"]),
        ("reference_missing", not reference),
        (
            "observation_evidence_missing",
            not all(
                work.get(k)
                for k in ("source_url", "evidence_excerpt", "verification_notes")
            ),
        ),
    ):
        if condition:
            missing.append(key)
    if prepared["contact_status"] != "eligible":
        missing.append("email_" + prepared["contact_status"])
    settings = session.scalar(select(SharedSettings))
    state = (settings.service_connection_state if settings else {}) or {}
    smtp = state.get("smtp", {})
    sender = {k: smtp.get(k) for k in ("username", "from_name", "reply_to")}
    profile_url = fields.profile_url or creator.canonical_url
    source = {
        k: work.get(k)
        for k in (
            "id",
            "source_url",
            "content_title",
            "work_name",
            "evidence_excerpt",
            "verification_notes",
            "timestamp_seconds",
        )
    }
    return {
        "selection_id": str(selection.id),
        "identity": prepared["identity"],
        "active": prepared["active"],
        "identity_changed": prepared["identity_changed"],
        "public_name": prepared["public_name"],
        "public_name_confirmed": prepared["public_name_confirmed"],
        "channel_name": prepared["name"],
        "profile_url": profile_url,
        "reference": reference,
        "work": source,
        "game": game,
        "selected_contact": prepared["selected_contact"],
        "contact_status": prepared["contact_status"],
        "template_version_id": str(template.id),
        "fixed_hash": template.fixed_hash,
        "sender": sender,
        "missing_fields": missing,
        "slot_sources": {
            "firstName": {
                "source_url": profile_url,
                "confirmed": prepared["public_name_confirmed"],
            },
            "channelName": {"source_url": profile_url},
            "reference": source,
            "observation": source,
        },
    }


def generation_ready(data):
    return not any(not item.startswith("email_") for item in data["missing_fields"])
