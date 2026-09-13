"""Source-bound personalization inputs, separate from historical recipient snapshots."""

from sqlalchemy import select
from app.api.routes.activity import _get
from app.db.models.activity_outreach import ActivitySelection, RecipientSnapshot
from app.db.models.discovery import Activity
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.settings import SharedSettings
from app.repositories.activity_preparation import preparation
from app.repositories.creator_library import effective_fields, work_detail
from app.repositories.library_v2 import game_detail
from app.outreach.evidence import choose_recorded_work
from app.outreach.prefill import (
    choose_prefill_work,
    slot_text,
    work_kind,
    work_observation,
)


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
    if not works and not selection.work_ids and not prepared["identity_changed"]:
        works = [
            work_detail(w, creator).model_dump(mode="json")
            for w in creator.works
            if w.identity_revision == creator.identity_revision
        ]
        references = {
            str(r.get("name", "")).casefold()
            for r in activity.source_snapshot.get("references", [])
        }
        for candidate in works:
            candidate["relation"] = (
                "current_game"
                if candidate.get("game_id") == str(activity.game_id)
                else (
                    "reference_game"
                    if (candidate.get("work_name") or "").casefold() in references
                    else "related_content"
                )
            )
            candidate["evidence_status"] = (
                "recorded_evidence"
                if work_kind(candidate) == "manual_note"
                else "metadata_only"
            )
    recorded_work = choose_recorded_work(works)
    work = choose_prefill_work(
        works, game, activity.source_snapshot.get("references", [])
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
    from app.outreach.game_template import game_template

    live_template = game_template(game, sender_name=sender.get("from_name"))
    if (
        template.source_metadata.get("kind") != "game_bound"
        or template.fixed_hash != live_template["fixed_hash"]
    ):
        missing.append("template_context_changed")
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
            "game_id",
            "relation",
            "evidence_status",
        )
    }
    source["evidence_tier"] = (
        work.get("relation", "related_content") if recorded_work else "unverified"
    )
    source["evidence_kind"] = work_kind(work)
    public_name = prepared["public_name"] or prepared["name"]
    prefill = {
        "firstName": slot_text(public_name),
        "channelName": slot_text(prepared["name"]),
        "reference": slot_text(reference),
        "observation": work_observation(work),
    }
    return {
        "selection_id": str(selection.id),
        "identity": prepared["identity"],
        "active": prepared["active"],
        "identity_changed": prepared["identity_changed"],
        "public_name": public_name,
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
        "prefill_values": prefill,
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
