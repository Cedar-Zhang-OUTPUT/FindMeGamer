"""Validate curated Twitch/Instagram materials and explicitly import a batch."""

import argparse
import json
from pathlib import Path
import sys

from sqlalchemy import select

from app.db.models.jobs import acquire_job_change_lock
from app.db.models.profiles import CreatorContact, CreatorProfile
from app.schemas.creator_import import CreatorImport


def import_profiles(
    session, data: CreatorImport, *, dry_run=False, on_conflict="error"
):
    """Caller owns commit. Savepoint makes every batch atomic on refusal/error."""
    if on_conflict not in {"error", "skip", "replace-unedited"}:
        raise ValueError("invalid conflict policy")
    reports = []
    with session.begin_nested():
        if not dry_run:
            acquire_job_change_lock(session)
        for record in data.records:
            result = {
                "platform": record.platform,
                "platform_account_id": record.platform_account_id,
            }
            reports.append(result)
            if not record.platform_account_id:
                result["status"] = "needs_identity_resolution"
                if not dry_run:
                    raise ValueError("identity resolution required before import")
                continue
            query = select(CreatorProfile).where(
                CreatorProfile.platform == record.platform,
                CreatorProfile.platform_account_id == record.platform_account_id,
            )
            profile = session.scalar(query if dry_run else query.with_for_update())
            material = record.model_dump(mode="json", exclude={"analysis"})
            analysis = (
                record.analysis.synthesis.model_dump(mode="json")
                if record.analysis
                else {}
            )
            if profile is not None:
                manual = bool(
                    profile.manual_overrides
                    or profile.manual_notes
                    or profile.profile_revision
                    or any(c.is_manual for c in profile.contacts)
                )
                same = (
                    profile.current_facts.get("curated_collection") == material
                    and profile.analysis == analysis
                    and profile.last_analyzed_at
                    == (record.analysis.analyzed_at if record.analysis else None)
                )
                if on_conflict == "skip":
                    result["status"] = "skipped"
                    continue
                if manual:
                    if not dry_run:
                        raise ValueError(
                            "manual profile conflict; use --on-conflict skip"
                        )
                    result["status"] = "manual_conflict"
                    continue
                if same:
                    result["status"] = "duplicate"
                    continue
                if (
                    on_conflict != "replace-unedited"
                    or "curated_import" not in profile.source_status
                ):
                    if not dry_run:
                        raise ValueError(
                            "existing profile conflict; explicitly skip or replace-unedited curated material"
                        )
                    result["status"] = "existing_conflict"
                    continue
                if profile.analysis and not record.analysis:
                    raise ValueError(
                        "cannot replace analyzed profile with fact-only material"
                    )
            if dry_run:
                result["status"] = "ready"
                continue
            if profile is None:
                profile = CreatorProfile(
                    platform=record.platform,
                    platform_account_id=record.platform_account_id,
                )
                session.add(profile)
            profile.canonical_url = record.profile_url
            profile.sort_name = record.display_name
            profile.current_facts = {
                "platform": record.platform,
                "platform_account_id": record.platform_account_id,
                "display_name": record.display_name,
                "username": record.username,
                "description": record.bio_original,
                "avatar_url": record.avatar_url,
                "followers_count": record.followers_count,
                "curated_collection": material,
            }
            profile.analysis = analysis
            profile.brief = analysis.get("creator_brief", {})
            profile.last_analyzed_at = (
                record.analysis.analyzed_at if record.analysis else None
            )
            profile.next_analysis_at = None
            profile.source_status = {
                record.platform: "unavailable",
                "live_collection": "unavailable",
                "curated_import": {
                    "status": "available",
                    "schema_version": 1,
                    "platform": record.platform,
                    "platform_account_id": record.platform_account_id,
                },
                "freshness": "current" if record.analysis else "unanalyzed",
            }
            profile.model_metadata = {"origin": "curated_import"}
            profile.prompt_metadata = {}
            session.flush()
            existing_emails = {c.email.casefold() for c in profile.contacts}
            for contact in record.contacts:
                if contact.email.casefold() not in existing_emails:
                    profile.contacts.append(
                        CreatorContact(
                            creator_id=profile.id,
                            email=contact.email,
                            purpose=contact.purpose,
                            source_type="curated_import",
                            source_url=contact.source_url,
                            is_manual=False,
                            validation_state="unverified",
                            is_active=True,
                        )
                    )
                    existing_emails.add(contact.email.casefold())
            session.flush()
            result["status"] = "imported"
    return reports


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--on-conflict", choices=("error", "skip", "replace-unedited"), default="error"
    )
    args = parser.parse_args(argv)
    try:
        data = CreatorImport.model_validate_json(args.file.read_text(encoding="utf-8"))
        if args.dry_run:
            # Offline dry-run never constructs DB/provider clients or reads secrets.
            reports = [
                {
                    "platform": r.platform,
                    "platform_account_id": r.platform_account_id,
                    "status": (
                        "ready"
                        if r.platform_account_id
                        else "needs_identity_resolution"
                    ),
                    "analysis_available": r.analysis is not None,
                }
                for r in data.records
            ]
        else:
            from app.core.database import session_scope

            with session_scope() as session:
                reports = import_profiles(session, data, on_conflict=args.on_conflict)
                session.commit()
        print(json.dumps({"dry_run": args.dry_run, "records": reports}))
        return 0
    except Exception:
        # Pydantic errors can embed rejected secrets. Never echo raw inputs/errors.
        print(
            "Import refused: invalid material, unresolved identity, or existing profile conflict. No batch was committed.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
