"""No-network backfill from already published YouTube work facts/checkpoints."""

import argparse
import json

from sqlalchemy import select
from app.db.models.enums import JobStatus
from app.db.models.jobs import AnalysisJob, CreatorAnalysisNode
from app.db.models.profiles import CreatorProfile, CreatorWork
from app.outreach.prefill import metadata_observation


def backfill_prefill(session, *, apply=False):
    report = {
        "profiles_scanned": 0,
        "works_to_update": 0,
        "works_updated": 0,
        "checkpoint_descriptions_used": 0,
    }
    profiles = session.scalars(
        select(CreatorProfile)
        .where(
            CreatorProfile.platform == "youtube",
            CreatorProfile.last_analyzed_at.is_not(None),
        )
        .order_by(CreatorProfile.id)
    ).all()
    for creator in profiles:
        report["profiles_scanned"] += 1
        # Only reuse the successful publication for the current account. Never pull
        # data from a failed reanalysis or a previous, manually replaced identity.
        payload = session.scalar(
            select(CreatorAnalysisNode.output_payload)
            .join(AnalysisJob, AnalysisJob.id == CreatorAnalysisNode.job_id)
            .where(
                AnalysisJob.profile_id == creator.id,
                AnalysisJob.status == JobStatus.SUCCEEDED,
                AnalysisJob.canonical_target_id == creator.platform_account_id,
                AnalysisJob.completed_at == creator.last_analyzed_at,
                CreatorAnalysisNode.node_key == "source:v1",
            )
            .order_by(AnalysisJob.created_at.desc())
            .limit(1)
        )
        videos = (
            {
                item["id"]: item
                for item in (payload or {}).get("videos", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            }
            if isinstance(payload, dict)
            and payload.get("channel_id") == creator.platform_account_id
            else {}
        )
        works = session.scalars(
            select(CreatorWork).where(
                CreatorWork.creator_id == creator.id,
                CreatorWork.identity_revision == creator.identity_revision,
                CreatorWork.origin == "source",
                CreatorWork.platform == "youtube",
            )
        ).all()
        for work in works:
            source = work.source_fields or {}
            if source.get("outreach_observation") or not source.get("source_url"):
                continue
            video = videos.get(work.source_content_id) or {}
            suggestion = metadata_observation(
                source.get("content_title"),
                video.get("description"),
                source["source_url"],
            )
            if not suggestion["text"]:
                continue
            report["works_to_update"] += 1
            if suggestion["source_field"] == "description":
                report["checkpoint_descriptions_used"] += 1
            if apply:
                work.source_fields = source | {"outreach_observation": suggestion}
                report["works_updated"] += 1
    if apply:
        session.flush()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist source-only additions; default is read-only",
    )
    args = parser.parse_args()
    from app.core.database import session_scope

    with session_scope() as session:
        print(json.dumps(backfill_prefill(session, apply=args.apply)))


if __name__ == "__main__":
    main()
