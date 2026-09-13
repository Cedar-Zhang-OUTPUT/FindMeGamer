"""Read-only qualification of every original member, never implicit exclusions."""

from collections import Counter
from sqlalchemy import select
from app.api.routes.activity import _get, _error
from app.api.routes.outreach import _public_smtp_metadata
from app.db.models.outreach_drafts import (
    OutreachComposition,
    OutreachDraft,
    OutreachTemplateVersion,
)
from app.db.models.discovery import Activity
from app.db.models.profiles import GameProfile
from app.discovery.evaluation_snapshot import digest
from app.repositories.outreach_drafts import draft_view, complete_values
from app.repositories.settings import SettingsRepository
from app.schemas.activity_sending import Qualification
from app.outreach.activity_invitation_identity import blocking_delivery


def account_state(session):
    repository = SettingsRepository(session)
    settings = repository.get_smtp_settings()
    public = _public_smtp_metadata(settings.service_connection_state.get("smtp"))
    configured = public is not None and repository.get_connection("smtp") is not None
    return public, configured


def qualify(session, composition_id, exclusions):
    composition = _get(session, OutreachComposition, composition_id)
    template = _get(session, OutreachTemplateVersion, composition.template_version_id)
    activity = _get(session, Activity, composition.activity_id)
    game = _get(session, GameProfile, activity.game_id)
    rows = session.scalars(
        select(OutreachDraft)
        .where(OutreachDraft.composition_id == composition_id)
        .order_by(OutreachDraft.input_order, OutreachDraft.id)
    ).all()
    excluded = {str(item.draft_id): item.reason for item in exclusions}
    if not set(excluded).issubset({str(row.id) for row in rows}):
        raise _error(
            422,
            "qualification_exclusion_unknown",
            "Exclude only members from this composition.",
        )
    public, configured = account_state(session)
    sender = {
        "address": public["username"] if public else None,
        "name": public["from_name"] if public else None,
        "reply_to": public["reply_to"] if public else None,
    }
    members = []
    for row in rows:
        draft = draft_view(session, row)
        missing = list(draft["missing_fields"])
        if draft["source_changed"]:
            missing.append("draft_sources_changed")
        if draft["status"] != "succeeded" or not complete_values(draft["values"]):
            missing.append("draft_not_complete")
        if not draft["sender_facts_valid"]:
            missing.append("sender_facts_unconfirmed")
        if not configured:
            missing.append("smtp_not_configured")
        if not sender["name"]:
            missing.append("sender_identity_missing")
        source_steam = template.source_metadata.get("steam_app_id")
        if template.game_id != activity.game_id or (
            source_steam and game.steam_app_id and source_steam != game.steam_app_id
        ):
            missing.append("template_game_mismatch")
        rendered = draft["rendered"] or {}
        contact = draft["input"].get("selected_contact") or {}
        identity = draft["input"]["identity"]
        previous = blocking_delivery(session, activity.id, identity)
        if previous:
            missing.append("already_invited")
        members.append(
            {
                "draft_id": draft["id"],
                "recipient_snapshot_id": draft["recipient_snapshot_id"],
                "identity": identity,
                "blocking_delivery_id": str(previous.id) if previous else None,
                "missing_fields": list(dict.fromkeys(missing)),
                "exclusion_reason": excluded.get(draft["id"]),
                "recipient_email": contact.get("email"),
                "subject": template.subject,
                "html": rendered.get("html"),
                "text": rendered.get("text"),
                "values": draft["values"],
                "slot_sources": draft["slot_sources"],
                "template_version_id": str(template.id),
                "fixed_hash": template.fixed_hash,
                "revision": draft["revision"],
                "context_token": draft["context_token"],
                "sender_facts": draft["sender_facts"],
            }
        )
    address_counts = Counter(
        m["recipient_email"].casefold()
        for m in members
        if m["recipient_email"] and not m["exclusion_reason"]
    )
    for member in members:
        if (
            not member["exclusion_reason"]
            and member["recipient_email"]
            and address_counts[member["recipient_email"].casefold()] > 1
        ):
            member["missing_fields"].append("duplicate_recipient_email")
        member["status"] = (
            "excluded"
            if member["exclusion_reason"]
            else "needs_repair" if member["missing_fields"] else "eligible"
        )
    counts = Counter(m["status"] for m in members)
    result = {
        "composition_id": str(composition.id),
        "activity_id": str(activity.id),
        "sending_account_token": digest({"public": public, "configured": configured}),
        "total_count": len(members),
        "eligible_count": counts["eligible"],
        "repair_count": counts["needs_repair"],
        "excluded_count": counts["excluded"],
        "sender": sender,
        "members": members,
        "send_ready": counts["eligible"] > 0 and not counts["needs_repair"],
    }
    result["qualification_token"] = digest(result)
    return Qualification.model_validate(result).model_dump(mode="json")
