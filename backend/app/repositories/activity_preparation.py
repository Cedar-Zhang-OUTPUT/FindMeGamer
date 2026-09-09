"""Effective preparation derived from Library; no implicit human confirmation."""

from uuid import UUID, uuid4
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from pydantic import EmailStr, TypeAdapter, ValidationError
from app.api.routes.activity import _error, _get
from app.db.models.discovery import Activity, DiscoveryCandidate, DiscoveryQuery
from app.db.models.activity_outreach import ActivitySelection
from app.db.models.profiles import CreatorProfile, GameProfile
from app.db.models.discovery_evaluation import EvaluationItem, EvaluationRun
from app.discovery.evaluation_snapshot import digest, creator_snapshot, game_data
from app.repositories.library_v2 import game_detail
from app.repositories.creator_library import effective_fields, work_detail
from app.repositories.discovery_evaluation import result_rows
from app.core.idempotency import utc_now
from app.core.creator_identity import creator_account_key
from app.schemas.activity_outreach import Preparation, PreparationContact


def identity(creator):
    return {
        "platform": creator.platform,
        "account_id": creator_account_key(creator),
        "revision": creator.identity_revision,
    }


def saved_identity(row):
    return {
        "platform": row.platform,
        "account_id": row.account_id,
        "revision": row.identity_revision,
    }


def get_selection(session, activity_id, selection_id):
    row = _get(session, ActivitySelection, selection_id)
    if row.activity_id != activity_id:
        raise _error(
            404, "selection_not_found", "Selection not found in this Activity."
        )
    return row


def contact_value(contact, creator):
    status = "eligible"
    try:
        TypeAdapter(EmailStr).validate_python(contact.email)
    except (ValidationError, ValueError):
        status = "invalid"
    if not contact.is_active:
        status = "inactive"
    if contact.identity_revision != creator.identity_revision:
        status = "historical"
    return jsonable_encoder(
        {
            "id": contact.id,
            "email": contact.email,
            "purpose": contact.purpose,
            "source_url": contact.source_url,
            "source_type": contact.source_type,
            "source_fields": contact.source_fields or {},
            "manual_overrides": contact.manual_overrides or {},
            "validation_state": contact.validation_state,
            "identity_revision": contact.identity_revision,
            "updated_at": contact.updated_at,
            "status": status,
        }
    )


def preparation(session, row):
    creator = _get(session, CreatorProfile, row.creator_id)
    fields = effective_fields(creator)
    changed = identity(creator) != saved_identity(row)
    contacts = sorted(
        (contact_value(c, creator) for c in creator.contacts), key=lambda c: c["id"]
    )
    contacts = [
        PreparationContact.model_validate(c).model_dump(mode="json") for c in contacts
    ]
    current_contact = next(
        (c for c in contacts if c["id"] == str(row.contact_id)), None
    )
    contact_status = "not_selected"
    if row.contact_id:
        contact_status = (
            "missing" if current_contact is None else current_contact["status"]
        )
        if contact_status == "eligible" and current_contact != row.contact_snapshot:
            contact_status = "changed"
    if changed and row.contact_id:
        contact_status = "historical"
    known = {
        str(w.id): work_detail(w, creator).model_dump(mode="json")
        for w in creator.works
        if w.identity_revision == row.identity_revision and not changed
    }
    works = [known[i] for i in row.work_ids if i in known]
    activity = _get(session, Activity, row.activity_id)
    game = _get(session, GameProfile, activity.game_id)
    current_game = game_detail(game).model_dump(mode="json")
    reference_ids = {r["id"] for r in activity.source_snapshot.get("references", [])}
    live_game = game_data(
        {
            "game": current_game,
            "references": [
                r for r in current_game["reference_works"] if r["id"] in reference_ids
            ],
        }
    )
    game_changed = digest(live_game) != digest(game_data(activity.source_snapshot))
    references = {
        str(r.get("name", "")).casefold()
        for r in activity.source_snapshot.get("references", [])
    }
    for work in works:
        work["relation"] = (
            "current_game"
            if work.get("game_id") == str(activity.game_id)
            else (
                "reference_game"
                if work.get("work_name") and work["work_name"].casefold() in references
                else "related_content"
            )
        )
        work["evidence_status"] = (
            "recorded_evidence"
            if work.get("evidence_excerpt") and work.get("verification_notes")
            else "metadata_only"
        )
    missing_works = [i for i in row.work_ids if i not in known]
    evaluation = None
    run = None
    if row.evaluation_item_id:
        item = session.get(EvaluationItem, row.evaluation_item_id)
        if item:
            run = session.get(EvaluationRun, item.run_id)
            evaluation = result_rows(session, run, [item])[0]
    name_key = digest({"identity": identity(creator), "name": fields.public_name})
    name_confirmed = bool(
        not changed
        and fields.public_name
        and row.name_confirmation.get("fingerprint") == name_key
    )
    missing = []
    if not row.active:
        missing.append("not_selected")
    if changed:
        missing.append("identity_changed")
    if game_changed:
        missing.append("game_changed")
    if contact_status != "eligible":
        missing.append("email_" + contact_status)
    if not name_confirmed:
        missing.append("public_name_unconfirmed")
    if not evaluation or not evaluation.get("match_brief"):
        missing.append("evaluation_missing")
    elif evaluation["identity_changed"]:
        missing.append("evaluation_identity_changed")
    elif evaluation["stale"]:
        missing.append("evaluation_stale")
    if not any(
        w.get("evidence_excerpt") and w.get("verification_notes") for w in works
    ):
        missing.append("evidence_missing")
    if not any(w["relation"] in {"current_game", "reference_game"} for w in works):
        missing.append("work_relation_missing")
    if missing_works:
        missing.append("work_missing")
    _, creator_fingerprint = creator_snapshot(creator, row.candidate_id)
    body = jsonable_encoder(
        {
            "id": row.id,
            "activity_id": row.activity_id,
            "creator_id": row.creator_id,
            "candidate_id": row.candidate_id,
            "active": row.active,
            "revision": row.revision,
            "identity": saved_identity(row),
            "identity_changed": changed,
            "name": fields.name if not changed else None,
            "public_name": fields.public_name if not changed else None,
            "public_name_confirmed": name_confirmed,
            "name_confirmed_at": (
                row.name_confirmation.get("at") if name_confirmed else None
            ),
            "contact_options": contacts if not changed else [],
            "selected_contact": row.contact_snapshot,
            "contact_status": contact_status,
            "works": works,
            "missing_work_ids": missing_works,
            "evaluation": evaluation,
            "evaluation_run_id": run.id if run else None,
            "missing_fields": missing,
            "freeze_ready": row.active,
            "send_ready": False,
            "sender_watched": False,
            "pending_send_requirements": [
                "complete_preparation",
                "template_and_content_validation",
                "sender_facts_confirmation",
                "sending_account_validation",
                "final_send_confirmation",
            ],
        }
    )
    body["game_changed"] = game_changed
    body["context_token"] = digest(
        {
            "preparation": body,
            "creator_fingerprint": creator_fingerprint,
            "game": live_game,
        }
    )
    return Preparation.model_validate(body).model_dump(mode="json")


def add_selection(session, activity_id, candidate_id):
    _get(session, Activity, activity_id)
    candidate = _get(session, DiscoveryCandidate, candidate_id)
    query = _get(session, DiscoveryQuery, candidate.query_id)
    if query.activity_id != activity_id:
        raise _error(
            422,
            "candidate_activity_mismatch",
            "Select a candidate discovered in this Activity.",
        )
    creator = _get(session, CreatorProfile, candidate.creator_id)
    expected = {
        "platform": candidate.platform,
        "account_id": candidate.account_id,
        "revision": candidate.identity_revision,
    }
    if identity(creator) != expected:
        raise _error(
            409,
            "selection_identity_changed",
            "This candidate belongs to a previous account identity.",
        )
    row = session.scalar(
        select(ActivitySelection).where(
            ActivitySelection.activity_id == activity_id,
            ActivitySelection.platform == candidate.platform,
            ActivitySelection.account_id == candidate.account_id,
        )
    )
    if row is None:
        row = ActivitySelection(
            id=uuid4(),
            activity_id=activity_id,
            creator_id=creator.id,
            candidate_id=candidate.id,
            platform=candidate.platform,
            account_id=candidate.account_id,
            identity_revision=candidate.identity_revision,
        )
        session.add(row)
    elif (
        row.creator_id != creator.id
        or row.identity_revision != creator.identity_revision
    ):
        if row.active:
            raise _error(
                409,
                "selection_identity_changed",
                "Cancel the old identity selection before explicitly adding the current candidate.",
            )
        row.creator_id, row.candidate_id, row.identity_revision = (
            creator.id,
            candidate.id,
            candidate.identity_revision,
        )
        row.contact_id, row.contact_snapshot, row.evaluation_item_id = None, None, None
        row.work_ids, row.name_confirmation = [], {}
        row.active = True
        row.revision += 1
    elif not row.active:
        row.active = True
        row.revision += 1
    session.flush()
    return preparation(session, row)


def check_revision(row, expected):
    if row.revision != expected:
        raise _error(
            409,
            "selection_revision_conflict",
            "Selection changed. Refresh before continuing.",
        )


def cancel_selection(session, row, value):
    check_revision(row, value.expected_revision)
    if row.active:
        row.active = False
        row.revision += 1
    session.flush()
    return preparation(session, row)


def update_selection(session, row, value):
    check_revision(row, value.expected_revision)
    before = preparation(session, row)
    if before["context_token"] != value.context_token:
        raise _error(
            409,
            "preparation_context_changed",
            "Source information changed. Read the current preparation before confirming it.",
        )
    if not row.active or before["identity_changed"]:
        raise _error(
            409,
            "selection_not_current",
            "Choose a current active account before preparing outreach.",
        )
    creator = _get(session, CreatorProfile, row.creator_id)
    if "contact_id" in value.model_fields_set:
        if value.contact_id is None:
            row.contact_id, row.contact_snapshot = None, None
        else:
            contact = next(
                (
                    c
                    for c in before["contact_options"]
                    if c["id"] == str(value.contact_id)
                ),
                None,
            )
            if contact is None or contact["status"] != "eligible":
                raise _error(
                    422,
                    "contact_not_eligible",
                    "Choose one current active valid email from this account.",
                )
            row.contact_id, row.contact_snapshot = value.contact_id, contact
    if "evaluation_run_id" in value.model_fields_set:
        row.evaluation_item_id = None
        if value.evaluation_run_id:
            run = session.get(EvaluationRun, value.evaluation_run_id)
            query = session.get(DiscoveryQuery, run.query_id) if run else None
            if query is None or query.activity_id != row.activity_id:
                raise _error(
                    422,
                    "evaluation_activity_mismatch",
                    "Choose an evaluation from this Activity.",
                )
            items = session.scalars(
                select(EvaluationItem).where(
                    EvaluationItem.run_id == run.id,
                    EvaluationItem.creator_id == row.creator_id,
                )
            ).all()
            item = next(
                (
                    i
                    for i in items
                    if i.snapshot.get("identity") == saved_identity(row)
                    and not i.identity_changed
                ),
                None,
            )
            if item is None:
                raise _error(
                    422,
                    "evaluation_identity_mismatch",
                    "Evaluation must describe this selected account identity.",
                )
            row.evaluation_item_id = item.id
    if "work_ids" in value.model_fields_set:
        known = {
            w.id for w in creator.works if w.identity_revision == row.identity_revision
        }
        if len(value.work_ids) != len(set(value.work_ids)) or not set(
            value.work_ids
        ).issubset(known):
            raise _error(
                422,
                "work_not_current",
                "Choose unique known works from this account identity.",
            )
        row.work_ids = [str(i) for i in value.work_ids]
    if "confirm_public_name" in value.model_fields_set:
        row.name_confirmation = {}
        if value.confirm_public_name:
            name = effective_fields(creator).public_name
            if not name:
                raise _error(
                    422,
                    "public_name_missing",
                    "Add a public name in Library before confirming it.",
                )
            row.name_confirmation = {
                "name": name,
                "identity": identity(creator),
                "fingerprint": digest({"identity": identity(creator), "name": name}),
                "at": utc_now().isoformat(),
            }
    row.revision += 1
    session.flush()
    return preparation(session, row)


def bulk_selection(session, activity_id, value):
    _get(session, Activity, activity_id)
    cancelled = []
    for choice in value.cancel_selections:
        row = get_selection(session, activity_id, choice.selection_id)
        cancel_selection(session, row, choice)
        cancelled.append(str(row.id))
    added = []
    for candidate_id in value.add_candidate_ids:
        current = add_selection(session, activity_id, candidate_id)
        if current["id"] in cancelled:
            raise _error(
                422,
                "selection_change_ambiguous",
                "Do not add and cancel the same account in one request.",
            )
        if current["id"] not in added:
            added.append(current["id"])
    return {"added_selection_ids": added, "cancelled_selection_ids": cancelled}
