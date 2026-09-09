"""Short evaluation transactions and public views; never Profile mutations."""

from collections import Counter
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.idempotency import utc_now
from app.db.models.discovery_evaluation import (
    EvaluationRun,
    EvaluationItem,
    EvaluationStep,
)
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.profiles import CreatorProfile, GameProfile
from app.discovery.evaluation_snapshot import (
    creator_snapshot,
    digest,
    evidence_rows,
    game_data,
)
from app.repositories.library_v2 import game_detail

METHOD_VERSION = "discovery-evaluation-v2-work-priority-chunk20"
MODELS = {
    "screening": "deepseek-v4-flash",
    "deep_match": "deepseek-v4-pro",
    "ranking": "deepseek-v4-pro",
}
CHUNK_SIZE = 20


def lock_run(session, identity):
    acquire_job_change_lock(session)
    return session.scalar(
        select(EvaluationRun)
        .where(EvaluationRun.id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def items_for(session, identity):
    return list(
        session.scalars(
            select(EvaluationItem)
            .where(EvaluationItem.run_id == identity)
            .order_by(EvaluationItem.input_order)
        )
    )


def steps_for(session, identity):
    return list(
        session.scalars(
            select(EvaluationStep)
            .where(EvaluationStep.run_id == identity)
            .order_by(EvaluationStep.step_key)
        )
    )


def expired(step):
    return (
        step.status == "running"
        and step.lease_expires_at is not None
        and step.lease_expires_at <= utc_now()
    )


def step_status(step):
    return "failed" if expired(step) else step.status


def add_step(session, run_id, key, kind, item_ids):
    step = EvaluationStep(
        id=uuid4(),
        run_id=run_id,
        step_key=key,
        kind=kind,
        item_ids=[str(i) for i in item_ids],
    )
    session.add(step)
    return step


def run_view(session, run):
    items, steps = items_for(session, run.id), steps_for(session, run.id)
    counts = Counter(step_status(s) for s in steps)
    matched = sum(i.match_brief is not None for i in items)
    status = run.status
    if (
        any(expired(s) for s in steps)
        and not counts["pending"]
        and not counts["running"]
    ):
        status = "partial" if matched else "failed"
    return {
        **{
            k: getattr(run, k)
            for k in (
                "id",
                "query_id",
                "stage",
                "method_version",
                "models",
                "conditions",
                "source_snapshot",
                "created_at",
            )
        },
        "status": status,
        "candidate_count": len(items),
        "matched_count": matched,
        "retryable": bool(counts["failed"] or run.status in {"queued", "running"})
        and not counts["running"],
        "usage": {
            "model_operations_started": sum(s.attempt for s in steps),
            "succeeded_steps": counts["succeeded"],
            "failed_steps": counts["failed"],
            "pending_steps": counts["pending"],
            "running_steps": counts["running"],
        },
        "steps": [
            {
                "id": s.id,
                "kind": s.kind,
                "status": step_status(s),
                "attempt": s.attempt,
                "error_code": (
                    "evaluation_outcome_unknown" if expired(s) else s.error_code
                ),
            }
            for s in steps
        ],
    }


def item_state(item, steps):
    if item.identity_changed:
        return "identity_changed"
    own = [s for s in steps if str(item.id) in s.item_ids]
    if item.screening_selected is False:
        return "screened_out"
    if item.match_brief is not None and item.score is not None:
        return "ranked"
    for kind in ("ranking", "deep_match", "screening"):
        stage = next((s for s in own if s.kind == kind), None)
        if stage is not None:
            if step_status(stage) == "failed":
                return f"{kind}_failed"
            if stage.status in {"pending", "running"}:
                return kind
    return "matched" if item.match_brief else "screening"


def result_rows(session, run, items):
    steps = steps_for(session, run.id)
    creators = {
        p.id: p
        for p in session.scalars(
            select(CreatorProfile)
            .where(CreatorProfile.id.in_([i.creator_id for i in items]))
            .options(selectinload(CreatorProfile.works))
        )
    }
    game = session.get(GameProfile, run.source_snapshot["game"]["id"])
    game_changed = True
    if game:
        detail = game_detail(game).model_dump(mode="json")
        wanted = {r["id"] for r in run.source_snapshot.get("references", [])}
        current = {
            "game": detail,
            "references": [r for r in detail["reference_works"] if r["id"] in wanted],
        }
        game_changed = digest(game_data(current)) != run.game_fingerprint
    result = []
    for item in items:
        creator = creators.get(item.creator_id)
        current, fingerprint = (
            creator_snapshot(creator, item.candidate_id) if creator else ({}, "")
        )
        identity_changed = item.identity_changed or current.get(
            "identity"
        ) != item.snapshot.get("identity")
        stale = identity_changed or game_changed or fingerprint != item.fingerprint
        evidence = evidence_rows(item.snapshot, item.match_brief, run.source_snapshot)
        evidence_status = (
            "recorded_evidence"
            if any(e["status"] == "recorded_evidence" for e in evidence)
            else "metadata_only" if item.snapshot.get("works") else "unknown"
        )
        fit_group = (
            "unranked"
            if item.score is None
            else (
                "strong_fit"
                if item.score >= 75
                else "potential_fit" if item.score >= 40 else "limited_fit"
            )
        )
        identity = item.snapshot["identity"]
        result.append(
            {
                "candidate_id": item.candidate_id,
                "creator_id": item.creator_id,
                "platform": identity["platform"],
                "account_id": identity["account_id"],
                "name": item.snapshot.get("creator_detail", {}).get("name"),
                "status": (
                    "identity_changed" if identity_changed else item_state(item, steps)
                ),
                "fit_group": fit_group,
                "match_brief": item.match_brief,
                "evidence_status": evidence_status,
                "evidence": evidence,
                "needs_enrichment": not item.snapshot.get("analysis_available", False)
                or evidence_status != "recorded_evidence",
                "stale": stale,
                "identity_changed": identity_changed,
                "sender_watched": False,
                "selected": False,
            }
        )
    return result
