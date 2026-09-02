"""Resumable initial Creator CSV seeding.

Report format version 1 stores the SHA-256 fingerprint of the exact UTF-8 CSV,
aggregate ``queued``/``duplicate``/``failed`` counts, and one ordered result for
every non-header record. Reports are replaced atomically after every completed
row. A matching report resumes only ``failed`` and ``incomplete`` rows.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import AbstractContextManager
import csv
from dataclasses import dataclass, replace
from datetime import UTC, datetime
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from typing import Literal, Protocol
from uuid import UUID, uuid4

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.targets import (
    CanonicalTarget,
    ChannelResolutionUnavailable,
    ChannelResolver,
    InvalidTarget,
    resolve_target,
)
from app.db.models.enums import JobMode, JobStatus, TargetType
from app.db.models.jobs import acquire_job_change_lock
from app.db.models.profiles import CreatorContact, CreatorProfile
from app.integrations.errors import PermanentIntegrationError
from app.repositories.jobs import JobsRepository


REPORT_FORMAT_VERSION = 1
SUPPORTED_HEADERS = frozenset({"youtube_url", "contact_email", "notes"})
FINAL_STATUSES = frozenset({"queued", "duplicate", "failed"})
RESOLVED_STATUSES = frozenset({"queued", "duplicate"})
MAX_NOTES_LENGTH = 20_000

RowStatus = Literal["incomplete", "queued", "duplicate", "failed"]
SessionFactory = Callable[[], AbstractContextManager[Session]]


class SeedCommandError(RuntimeError):
    """A safe, operator-readable fatal command error."""


@dataclass(frozen=True, slots=True)
class SeedRowError:
    code: str
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not 1 <= len(self.code) <= 128:
            raise ValueError("invalid seed row error code")
        if not isinstance(self.message, str) or not 1 <= len(self.message) <= 512:
            raise ValueError("invalid seed row error message")

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True, slots=True)
class SeedRowResult:
    row_number: int
    youtube_url: str
    contact_email: str | None
    notes: str | None
    status: RowStatus = "incomplete"
    canonical_channel_id: str | None = None
    canonical_url: str | None = None
    job_id: UUID | None = None
    profile_id: UUID | None = None
    error: SeedRowError | None = None

    def completed(
        self,
        *,
        status: Literal["queued", "duplicate", "failed"],
        contact_email: str | None = None,
        canonical_channel_id: str | None = None,
        canonical_url: str | None = None,
        job_id: UUID | None = None,
        profile_id: UUID | None = None,
        error: SeedRowError | None = None,
    ) -> "SeedRowResult":
        return replace(
            self,
            status=status,
            contact_email=contact_email,
            canonical_channel_id=canonical_channel_id,
            canonical_url=canonical_url,
            job_id=job_id,
            profile_id=profile_id,
            error=error,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "row_number": self.row_number,
            "youtube_url": self.youtube_url,
            "contact_email": self.contact_email,
            "notes": self.notes,
            "status": self.status,
            "canonical_channel_id": self.canonical_channel_id,
            "canonical_url": self.canonical_url,
            "job_id": str(self.job_id) if self.job_id is not None else None,
            "profile_id": (
                str(self.profile_id) if self.profile_id is not None else None
            ),
            "error": self.error.to_dict() if self.error is not None else None,
        }


@dataclass(slots=True)
class SeedReport:
    source_fingerprint: str
    rows: list[SeedRowResult]
    format_version: int = REPORT_FORMAT_VERSION

    @property
    def counts(self) -> dict[str, int]:
        return {
            "queued": sum(row.status == "queued" for row in self.rows),
            "duplicate": sum(row.status == "duplicate" for row in self.rows),
            "failed": sum(row.status == "failed" for row in self.rows),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "format_version": self.format_version,
            "source_fingerprint": self.source_fingerprint,
            "counts": self.counts,
            "rows": [row.to_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class SeedSource:
    fingerprint: str
    rows: tuple[SeedRowResult, ...]


@dataclass(frozen=True, slots=True)
class SeedCommitResult:
    created: bool
    job_id: UUID | None
    profile_id: UUID | None

    def __post_init__(self) -> None:
        if self.created and (self.job_id is None or self.profile_id is None):
            raise ValueError("created seed rows require Job and Profile IDs")


class CreatorSeedStore(Protocol):
    def prepare(
        self,
        target: CanonicalTarget,
        *,
        contact_email: str | None,
        notes: str | None,
        correlation_id: UUID,
    ) -> SeedCommitResult: ...

    def mark_queue_failure(self, job_id: UUID) -> None: ...


class JobDispatcher(Protocol):
    def dispatch(self, job_id: UUID) -> None: ...


class AtomicReportWriter:
    def __init__(
        self,
        *,
        replace: Callable[[os.PathLike[str], os.PathLike[str]], None] = os.replace,
    ) -> None:
        self._replace = replace

    def write(self, path: Path, report: SeedReport) -> None:
        parent = path.parent
        if parent != Path("."):
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                raise SeedCommandError(
                    "The report directory could not be created."
                ) from None
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(
                    report.to_dict(),
                    temporary,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                temporary.write("\n")
                temporary.flush()
                os.fsync(temporary.fileno())
            self._replace(temporary_path, path)
            temporary_path = None
        except SeedCommandError:
            raise
        except Exception:
            raise SeedCommandError(
                "The seed report could not be written safely."
            ) from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


class PostgresCreatorSeedStore:
    """Persist one seed row and its normal Creator Analysis Job atomically."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def prepare(
        self,
        target: CanonicalTarget,
        *,
        contact_email: str | None,
        notes: str | None,
        correlation_id: UUID,
    ) -> SeedCommitResult:
        if (
            target.target_type is not TargetType.CREATOR
            or target.requires_resolution
            or not isinstance(correlation_id, UUID)
            or correlation_id.version != 4
        ):
            raise ValueError("invalid Creator seed identity")
        with self._session_factory() as session:
            try:
                acquire_job_change_lock(session)
                profile = session.scalar(
                    select(CreatorProfile)
                    .where(CreatorProfile.youtube_channel_id == target.canonical_id)
                    .with_for_update()
                )
                repository = JobsRepository(session)
                active = repository.active_job(target)
                if profile is not None and profile.last_analyzed_at is not None:
                    session.commit()
                    return SeedCommitResult(
                        created=False,
                        job_id=active.id if active is not None else None,
                        profile_id=profile.id,
                    )
                if active is not None:
                    session.commit()
                    return SeedCommitResult(
                        created=False,
                        job_id=active.id,
                        profile_id=profile.id if profile is not None else None,
                    )
                if profile is not None and profile.source_status != {
                    "seed": "incomplete"
                }:
                    session.commit()
                    return SeedCommitResult(
                        created=False,
                        job_id=None,
                        profile_id=profile.id,
                    )
                if profile is None:
                    profile = CreatorProfile(
                        youtube_channel_id=target.canonical_id,
                        canonical_url=target.canonical_url,
                        sort_name=target.canonical_id,
                        current_facts={},
                        analysis={},
                        brief={},
                        source_status={"seed": "incomplete"},
                        model_metadata={},
                        prompt_metadata={},
                        manual_notes=notes,
                        last_analyzed_at=None,
                        next_analysis_at=None,
                    )
                    session.add(profile)
                    session.flush()
                    if contact_email is not None:
                        session.add(
                            CreatorContact(
                                creator_id=profile.id,
                                email=contact_email,
                                source_type="manual",
                                source_url=None,
                                is_manual=True,
                                validation_state="unverified",
                                priority=0,
                                is_active=True,
                            )
                        )
                result = repository.create_creator_seed_job(
                    target,
                    correlation_id=str(correlation_id),
                )
                if not result.created or result.job is None:
                    session.commit()
                    return SeedCommitResult(
                        created=False,
                        job_id=result.job.id if result.job is not None else None,
                        profile_id=profile.id,
                    )
                session.flush()
                job_id = result.job.id
                profile_id = profile.id
                session.commit()
                return SeedCommitResult(
                    created=True,
                    job_id=job_id,
                    profile_id=profile_id,
                )
            except Exception:
                session.rollback()
                raise

    def mark_queue_failure(self, job_id: UUID) -> None:
        from app.core.analysis_job_contract import QUEUE_FAILURE_MESSAGE
        from app.workers.analysis_tasks import (
            TerminalFailure,
            write_queued_publication_failure,
        )

        write_queued_publication_failure(
            job_id,
            TerminalFailure(
                code="analysis_queue_unavailable",
                message=QUEUE_FAILURE_MESSAGE,
                retryable=True,
            ),
            session_factory=self._session_factory,
            clock=self._clock,
        )


class CreatorSeedService:
    def __init__(
        self,
        *,
        store: CreatorSeedStore,
        resolver: ChannelResolver,
        dispatcher: JobDispatcher,
        report_writer: AtomicReportWriter | None = None,
    ) -> None:
        self.store = store
        self.resolver = resolver
        self.dispatcher = dispatcher
        self.report_writer = report_writer or AtomicReportWriter()

    def initialize_report(self, csv_path: Path, report_path: Path) -> SeedReport:
        source = load_seed_source(csv_path)
        report = SeedReport(
            source_fingerprint=source.fingerprint,
            rows=list(source.rows),
        )
        self.report_writer.write(report_path, report)
        return report

    def run(self, csv_path: Path, report_path: Path) -> SeedReport:
        csv_path = Path(csv_path)
        report_path = Path(report_path)
        _require_distinct_paths(csv_path, report_path)
        source = load_seed_source(csv_path)
        if report_path.exists():
            report = load_seed_report(report_path, source=source)
        else:
            report = SeedReport(
                source_fingerprint=source.fingerprint,
                rows=list(source.rows),
            )
            self.report_writer.write(report_path, report)

        seen: dict[str, tuple[UUID | None, UUID | None]] = {}
        for index, row in enumerate(report.rows):
            if row.status in RESOLVED_STATUSES:
                if row.canonical_channel_id is not None:
                    seen.setdefault(
                        row.canonical_channel_id,
                        (row.profile_id, row.job_id),
                    )
                continue
            completed = self._process_row(row, seen=seen)
            report.rows[index] = completed
            self.report_writer.write(report_path, report)
        return report

    def _process_row(
        self,
        row: SeedRowResult,
        *,
        seen: dict[str, tuple[UUID | None, UUID | None]],
    ) -> SeedRowResult:
        email, email_error = _normalized_email(row.contact_email)
        if email_error is not None:
            return row.completed(
                status="failed",
                contact_email=row.contact_email,
                error=email_error,
            )
        if row.notes is not None and len(row.notes) > MAX_NOTES_LENGTH:
            return row.completed(
                status="failed",
                contact_email=email,
                error=SeedRowError(
                    "notes_too_long",
                    "Notes must contain no more than 20,000 characters.",
                ),
            )
        try:
            target = resolve_target(
                TargetType.CREATOR,
                row.youtube_url,
                self.resolver,
            )
        except InvalidTarget:
            return row.completed(
                status="failed",
                contact_email=email,
                error=SeedRowError(
                    "youtube_url_invalid",
                    "The YouTube URL is invalid or unsupported.",
                ),
            )
        except ChannelResolutionUnavailable:
            return row.completed(
                status="failed",
                contact_email=email,
                error=SeedRowError(
                    "channel_resolution_unavailable",
                    "YouTube Handle resolution is temporarily unavailable.",
                ),
            )
        except PermanentIntegrationError:
            return row.completed(
                status="failed",
                contact_email=email,
                error=SeedRowError(
                    "youtube_resolution_failed",
                    "The YouTube Channel could not be resolved.",
                ),
            )
        except Exception:
            return row.completed(
                status="failed",
                contact_email=email,
                error=SeedRowError(
                    "youtube_resolution_failed",
                    "The YouTube Channel could not be resolved.",
                ),
            )

        owner = seen.get(target.canonical_id)
        if owner is not None:
            return row.completed(
                status="duplicate",
                contact_email=email,
                canonical_channel_id=target.canonical_id,
                canonical_url=target.canonical_url,
                profile_id=owner[0],
                job_id=owner[1],
            )
        seen[target.canonical_id] = (None, None)

        try:
            committed = self.store.prepare(
                target,
                contact_email=email,
                notes=row.notes,
                correlation_id=uuid4(),
            )
        except Exception:
            return row.completed(
                status="failed",
                contact_email=email,
                canonical_channel_id=target.canonical_id,
                canonical_url=target.canonical_url,
                error=SeedRowError(
                    "seed_database_unavailable",
                    "The Creator seed row could not be saved. Please retry.",
                ),
            )

        seen[target.canonical_id] = (committed.profile_id, committed.job_id)
        if not committed.created:
            return row.completed(
                status="duplicate",
                contact_email=email,
                canonical_channel_id=target.canonical_id,
                canonical_url=target.canonical_url,
                job_id=committed.job_id,
                profile_id=committed.profile_id,
            )
        assert committed.job_id is not None
        try:
            self.dispatcher.dispatch(committed.job_id)
        except Exception:
            try:
                self.store.mark_queue_failure(committed.job_id)
            except Exception:
                pass
            return row.completed(
                status="failed",
                contact_email=email,
                canonical_channel_id=target.canonical_id,
                canonical_url=target.canonical_url,
                job_id=committed.job_id,
                profile_id=committed.profile_id,
                error=SeedRowError(
                    "analysis_queue_unavailable",
                    "Analysis could not be queued. Please retry.",
                ),
            )
        return row.completed(
            status="queued",
            contact_email=email,
            canonical_channel_id=target.canonical_id,
            canonical_url=target.canonical_url,
            job_id=committed.job_id,
            profile_id=committed.profile_id,
        )


def _normalized_email(
    raw_email: str | None,
) -> tuple[str | None, SeedRowError | None]:
    if raw_email is None or raw_email == "":
        return None, None
    try:
        normalized = validate_email(
            raw_email,
            check_deliverability=False,
        ).normalized
    except EmailNotValidError:
        return None, SeedRowError(
            "contact_email_invalid",
            "The optional contact email is invalid.",
        )
    return normalized, None


def _require_distinct_paths(csv_path: Path, report_path: Path) -> None:
    try:
        same = csv_path.resolve(strict=False) == report_path.resolve(strict=False)
    except OSError:
        same = os.path.abspath(csv_path) == os.path.abspath(report_path)
    if same:
        raise SeedCommandError("The CSV and report paths must be different.")


def load_seed_source(csv_path: Path) -> SeedSource:
    try:
        raw = Path(csv_path).read_bytes()
    except OSError:
        raise SeedCommandError("The Creator seed CSV could not be read.") from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise SeedCommandError("The Creator seed CSV must use UTF-8.") from None
    try:
        records = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error:
        raise SeedCommandError("The Creator seed CSV is invalid.") from None
    if not records:
        raise SeedCommandError("The Creator seed CSV must include a header row.")
    header = records[0]
    if header.count("youtube_url") == 0:
        raise SeedCommandError("The CSV header must include youtube_url.")
    if header.count("youtube_url") > 1:
        raise SeedCommandError("The CSV header contains duplicate youtube_url columns.")
    if len(header) != len(set(header)):
        raise SeedCommandError("The CSV header contains a duplicate column.")
    unknown = [name for name in header if name not in SUPPORTED_HEADERS]
    if unknown:
        raise SeedCommandError("The CSV header contains an unsupported column.")

    rows: list[SeedRowResult] = []
    for row_number, values in enumerate(records[1:], start=2):
        mapped = dict(zip(header, values, strict=False))
        if len(values) != len(header):
            mapped["youtube_url"] = ""
        email = mapped.get("contact_email") or None
        notes = mapped.get("notes")
        rows.append(
            SeedRowResult(
                row_number=row_number,
                youtube_url=mapped.get("youtube_url", ""),
                contact_email=email,
                notes=notes if notes not in (None, "") else None,
            )
        )
    fingerprint = "sha256:" + hashlib.sha256(raw).hexdigest()
    return SeedSource(fingerprint=fingerprint, rows=tuple(rows))


def load_seed_report(path: Path, *, source: SeedSource) -> SeedReport:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("format_version") != REPORT_FORMAT_VERSION
            or payload.get("source_fingerprint") != source.fingerprint
            or not isinstance(payload.get("rows"), list)
        ):
            raise ValueError
        if payload.get("source_fingerprint") != source.fingerprint:
            raise ValueError
        raw_rows = payload["rows"]
        if len(raw_rows) != len(source.rows):
            raise ValueError
        rows = [_row_from_report(value) for value in raw_rows]
        if any(
            stored.row_number != original.row_number
            or stored.youtube_url != original.youtube_url
            or stored.notes != original.notes
            for stored, original in zip(rows, source.rows, strict=True)
        ):
            raise ValueError
        report = SeedReport(source_fingerprint=source.fingerprint, rows=rows)
        if payload.get("counts") != report.counts:
            raise ValueError
        return report
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SeedCommandError("The existing seed report is invalid.") from None
    except ValueError:
        try:
            different = (
                json.loads(path.read_text(encoding="utf-8")).get("source_fingerprint")
                != source.fingerprint
            )
        except Exception:
            different = False
        message = (
            "The existing seed report belongs to a different CSV."
            if different
            else "The existing seed report is invalid."
        )
        raise SeedCommandError(message) from None


def _row_from_report(value: object) -> SeedRowResult:
    if not isinstance(value, dict):
        raise ValueError
    expected = {
        "row_number",
        "youtube_url",
        "contact_email",
        "notes",
        "status",
        "canonical_channel_id",
        "canonical_url",
        "job_id",
        "profile_id",
        "error",
    }
    if set(value) != expected or value["status"] not in FINAL_STATUSES | {"incomplete"}:
        raise ValueError
    error_value = value["error"]
    error = None
    if error_value is not None:
        if not isinstance(error_value, dict) or set(error_value) != {
            "code",
            "message",
        }:
            raise ValueError
        error = SeedRowError(error_value["code"], error_value["message"])
    return SeedRowResult(
        row_number=value["row_number"],
        youtube_url=value["youtube_url"],
        contact_email=value["contact_email"],
        notes=value["notes"],
        status=value["status"],
        canonical_channel_id=value["canonical_channel_id"],
        canonical_url=value["canonical_url"],
        job_id=UUID(value["job_id"]) if value["job_id"] is not None else None,
        profile_id=(
            UUID(value["profile_id"]) if value["profile_id"] is not None else None
        ),
        error=error,
    )


def build_production_service() -> CreatorSeedService:
    """Construct settings, database, YouTube, and Celery dependencies lazily."""
    from app.analysis.runtime import build_production_channel_resolver
    from app.api.routes.jobs import CeleryJobDispatcher
    from app.core.database import session_scope

    return CreatorSeedService(
        store=PostgresCreatorSeedStore(session_factory=session_scope),
        resolver=build_production_channel_resolver(session_factory=session_scope),
        dispatcher=CeleryJobDispatcher(),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.seed_creators",
        description="Seed initial YouTube Creators from a resumable UTF-8 CSV.",
    )
    parser.add_argument("csv_path", metavar="<csv-path>", type=Path)
    parser.add_argument(
        "--report",
        required=True,
        metavar="<json-path>",
        type=Path,
        help="Atomic JSON progress report path.",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    service_factory: Callable[[], CreatorSeedService] = build_production_service,
) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        service = service_factory()
        report = service.run(arguments.csv_path, arguments.report)
    except SeedCommandError as error:
        print(f"Error: {error}", file=os.sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "Interrupted. Resume with the same CSV and report paths.",
            file=os.sys.stderr,
        )
        return 130
    except Exception:
        print("Error: Creator seeding could not be started safely.", file=os.sys.stderr)
        return 2
    print(json.dumps(report.counts, sort_keys=True))
    return 1 if report.counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AtomicReportWriter",
    "build_parser",
    "build_production_service",
    "CreatorSeedService",
    "load_seed_report",
    "load_seed_source",
    "main",
    "PostgresCreatorSeedStore",
    "SeedCommandError",
    "SeedCommitResult",
    "SeedReport",
    "SeedRowError",
    "SeedRowResult",
]
