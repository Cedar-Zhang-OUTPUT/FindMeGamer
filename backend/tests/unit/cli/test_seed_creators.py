from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from uuid import UUID, uuid4

import pytest

from app.analysis.targets import CanonicalTarget
from app.db.models.enums import TargetType
from app.integrations.errors import PermanentIntegrationError


BACKEND_ROOT = Path(__file__).resolve().parents[3]
CHANNEL_ALPHA = "UCalpha123"
CHANNEL_BETA = "UCbeta1234"


@pytest.fixture
def seed_module():
    return importlib.import_module("app.cli.seed_creators")


class Resolver:
    def __init__(self) -> None:
        self.calls: list[CanonicalTarget] = []
        self.errors: dict[str, BaseException] = {}

    def resolve_channel(self, target: CanonicalTarget) -> str:
        self.calls.append(target)
        error = self.errors.get(target.canonical_id)
        if error is not None:
            raise error
        return {
            "@alpha": CHANNEL_ALPHA,
            "@beta": CHANNEL_BETA,
        }.get(target.canonical_id, target.canonical_id)


class Store:
    def __init__(self, seed_module) -> None:
        self._module = seed_module
        self.calls: list[tuple[str, str | None, str | None, UUID]] = []
        self.failures: list[UUID] = []
        self.events: list[str] = []
        self.error: BaseException | None = None
        self.results: list[object] = []

    def prepare(
        self,
        target: CanonicalTarget,
        *,
        contact_email: str | None,
        notes: str | None,
        correlation_id: UUID,
    ):
        self.events.append("commit")
        self.calls.append((target.canonical_id, contact_email, notes, correlation_id))
        if self.error is not None:
            raise self.error
        if self.results:
            return self.results.pop(0)
        return self._module.SeedCommitResult(
            created=True,
            job_id=uuid4(),
            profile_id=uuid4(),
        )

    def mark_queue_failure(self, job_id: UUID) -> None:
        self.failures.append(job_id)


class Dispatcher:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.calls: list[UUID] = []
        self.error: BaseException | None = None

    def dispatch(self, job_id: UUID) -> None:
        assert self.store.events[-1] == "commit"
        self.store.events.append("publish")
        self.calls.append(job_id)
        if self.error is not None:
            raise self.error


def write_csv(tmp_path: Path, text: str, *, name: str = "creators.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def service(seed_module, *, store=None, resolver=None, dispatcher=None):
    effective_store = store or Store(seed_module)
    effective_resolver = resolver or Resolver()
    effective_dispatcher = dispatcher or Dispatcher(effective_store)
    return (
        seed_module.CreatorSeedService(
            store=effective_store,
            resolver=effective_resolver,
            dispatcher=effective_dispatcher,
        ),
        effective_store,
        effective_resolver,
        effective_dispatcher,
    )


def test_module_import_is_lazy_and_network_safe() -> None:
    script = """
import os
import socket

os.environ.pop("WORKSPACE_ACCESS_KEY_HASH", None)
os.environ["DATABASE_URL"] = "postgresql+psycopg://must-not-connect.invalid/db"

def blocked(*args, **kwargs):
    raise AssertionError("network access during seed command import")

socket.create_connection = blocked
socket.socket.connect = blocked
import app.cli.seed_creators
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_cli_help_exposes_exact_entrypoint_and_required_report() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "app.cli.seed_creators", "--help"],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "python -m app.cli.seed_creators" in completed.stdout
    assert "<csv-path>" in completed.stdout
    assert "--report <json-path>" in completed.stdout
    assert completed.stderr == ""


def test_main_exit_is_zero_only_when_current_run_has_no_failed_rows(
    seed_module, tmp_path, capsys
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n",
    )
    report_path = tmp_path / "report.json"
    successful, *_ = service(seed_module)

    assert (
        seed_module.main(
            [str(csv_path), "--report", str(report_path)],
            service_factory=lambda: successful,
        )
        == 0
    )
    output = capsys.readouterr()
    assert '"queued": 1' in output.out
    assert output.err == ""

    failed_csv = write_csv(
        tmp_path,
        "youtube_url\nnot-a-url\n",
        name="failed.csv",
    )
    failed_service, *_ = service(seed_module)
    assert (
        seed_module.main(
            [str(failed_csv), "--report", str(tmp_path / "failed.json")],
            service_factory=lambda: failed_service,
        )
        == 1
    )
    output = capsys.readouterr()
    assert '"failed": 1' in output.out
    assert output.err == ""


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("contact_email,notes\n", "youtube_url"),
        ("youtube_url,youtube_url\n", "duplicate"),
    ],
)
def test_invalid_required_header_fails_before_dependencies(
    seed_module, tmp_path, header, message
) -> None:
    csv_path = write_csv(tmp_path, header)
    runner, store, resolver, dispatcher = service(seed_module)

    with pytest.raises(seed_module.SeedCommandError, match=message):
        runner.run(csv_path, tmp_path / "report.json")

    assert resolver.calls == []
    assert store.calls == []
    assert dispatcher.calls == []


def test_optional_headers_may_be_omitted(seed_module, tmp_path) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n",
    )
    runner, store, _, _ = service(seed_module)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert result.counts == {"queued": 1, "duplicate": 0, "failed": 0}
    assert store.calls[0][1:3] == (None, None)


def test_same_csv_and_report_path_is_rejected_before_mutation(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(tmp_path, "youtube_url\n")
    runner, store, resolver, dispatcher = service(seed_module)

    with pytest.raises(seed_module.SeedCommandError, match="different"):
        runner.run(csv_path, csv_path)

    assert resolver.calls == []
    assert store.calls == []
    assert dispatcher.calls == []


def test_email_is_normalized_notes_are_preserved_and_bad_rows_continue(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url,contact_email,notes\n"
        "https://youtube.com/@alpha,Alpha@EXAMPLE.COM,温暖的线索\n"
        "https://youtube.com/@bad,bad-address,Keep going\n"
        "https://youtube.com/@beta,,Final row\n",
    )
    runner, store, resolver, dispatcher = service(seed_module)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert result.counts == {"queued": 2, "duplicate": 0, "failed": 1}
    assert [row.status for row in result.rows] == ["queued", "failed", "queued"]
    assert result.rows[0].contact_email == "Alpha@example.com"
    assert result.rows[0].notes == "温暖的线索"
    assert result.rows[1].error.code == "contact_email_invalid"
    assert [call[:3] for call in store.calls] == [
        (CHANNEL_ALPHA, "Alpha@example.com", "温暖的线索"),
        (CHANNEL_BETA, None, "Final row"),
    ]
    assert len(resolver.calls) == 2
    assert len(dispatcher.calls) == 2


def test_invalid_email_remains_failed_with_original_input_on_resume(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url,contact_email,notes\n"
        "https://youtube.com/@alpha,bad-address,Keep for correction\n",
    )
    report_path = tmp_path / "report.json"
    first_runner, first_store, _, first_dispatcher = service(seed_module)

    first = first_runner.run(csv_path, report_path)

    assert first.rows[0].status == "failed"
    assert first.rows[0].contact_email == "bad-address"
    assert first_store.calls == []
    assert first_dispatcher.calls == []

    resumed_runner, resumed_store, _, resumed_dispatcher = service(seed_module)
    resumed = resumed_runner.run(csv_path, report_path)

    assert resumed.rows[0].status == "failed"
    assert resumed.rows[0].contact_email == "bad-address"
    assert resumed_store.calls == []
    assert resumed_dispatcher.calls == []


def test_quoted_multiline_notes_are_preserved_verbatim(seed_module, tmp_path) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url,contact_email,notes\n"
        'https://youtube.com/@alpha,alpha@example.com,"Line one\nLine two"\n',
    )
    runner, store, _, _ = service(seed_module)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert result.rows[0].notes == "Line one\nLine two"
    assert store.calls[0][2] == "Line one\nLine two"


def test_blank_and_unsupported_urls_fail_per_row_without_stopping(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\n\nhttps://example.com/private\n"
        "https://www.youtube.com/channel/UCalpha123\n",
    )
    runner, store, _, dispatcher = service(seed_module)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert [row.status for row in result.rows] == ["failed", "failed", "queued"]
    assert all(row.error.code == "youtube_url_invalid" for row in result.rows[:2])
    assert len(store.calls) == len(dispatcher.calls) == 1


def test_handle_and_channel_aliases_resolve_to_one_first_row_owner(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url,contact_email,notes\n"
        "https://youtube.com/@alpha,first@example.com,First\n"
        "https://www.youtube.com/channel/UCalpha123,later@example.com,Later\n",
    )
    runner, store, resolver, dispatcher = service(seed_module)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert result.counts == {"queued": 1, "duplicate": 1, "failed": 0}
    assert [row.status for row in result.rows] == ["queued", "duplicate"]
    assert result.rows[0].contact_email == "first@example.com"
    assert result.rows[1].canonical_channel_id == CHANNEL_ALPHA
    assert [call[:3] for call in store.calls] == [
        (CHANNEL_ALPHA, "first@example.com", "First")
    ]
    assert len(resolver.calls) == 1
    assert len(dispatcher.calls) == 1


def test_existing_profile_or_active_job_is_duplicate_and_never_published(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n"
        "https://www.youtube.com/channel/UCbeta1234\n",
    )
    store = Store(seed_module)
    store.results = [
        seed_module.SeedCommitResult(created=False, profile_id=uuid4(), job_id=None),
        seed_module.SeedCommitResult(created=False, profile_id=None, job_id=uuid4()),
    ]
    runner, _, _, dispatcher = service(seed_module, store=store)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert result.counts == {"queued": 0, "duplicate": 2, "failed": 0}
    assert dispatcher.calls == []


def test_database_failure_publishes_nothing_and_later_row_continues(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n"
        "https://www.youtube.com/channel/UCbeta1234\n",
    )
    store = Store(seed_module)
    first = True

    original_prepare = store.prepare

    def prepare(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            raise RuntimeError("database password=never-print")
        return original_prepare(*args, **kwargs)

    store.prepare = prepare
    runner, _, _, dispatcher = service(seed_module, store=store)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert [row.status for row in result.rows] == ["failed", "queued"]
    assert result.rows[0].error.code == "seed_database_unavailable"
    assert len(dispatcher.calls) == 1
    assert "never-print" not in json.dumps(result.to_dict())


def test_broker_failure_converges_job_and_continues_without_secret_output(
    seed_module, tmp_path, capsys
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n"
        "https://www.youtube.com/channel/UCbeta1234\n",
    )
    runner, store, _, dispatcher = service(seed_module)
    first = True
    original_dispatch = dispatcher.dispatch

    def dispatch(job_id):
        nonlocal first
        if first:
            first = False
            dispatcher.calls.append(job_id)
            raise RuntimeError("redis://:broker-secret@localhost/0")
        original_dispatch(job_id)

    dispatcher.dispatch = dispatch

    result = runner.run(csv_path, tmp_path / "report.json")

    assert [row.status for row in result.rows] == ["failed", "queued"]
    assert result.rows[0].error.code == "analysis_queue_unavailable"
    assert store.failures == [dispatcher.calls[0]]
    assert "broker-secret" not in json.dumps(result.to_dict())
    assert "broker-secret" not in capsys.readouterr().out


def test_resolver_exception_is_safe_and_later_row_continues(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://youtube.com/@alpha\nhttps://youtube.com/@beta\n",
    )
    resolver = Resolver()
    resolver.errors["@alpha"] = PermanentIntegrationError(
        "youtube_channel_not_found secret=never-report"
    )
    runner, store, _, dispatcher = service(seed_module, resolver=resolver)

    result = runner.run(csv_path, tmp_path / "report.json")

    assert [row.status for row in result.rows] == ["failed", "queued"]
    assert result.rows[0].error.code == "youtube_resolution_failed"
    assert "never-report" not in json.dumps(result.to_dict())
    assert len(store.calls) == len(dispatcher.calls) == 1


def test_initial_and_per_row_reports_are_atomic_deterministic_and_valid(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n"
        "https://www.youtube.com/channel/UCbeta1234\n",
    )
    snapshots: list[dict[str, object]] = []

    class RecordingWriter:
        def __init__(self) -> None:
            self.delegate = seed_module.AtomicReportWriter()

        def write(self, path, report) -> None:
            self.delegate.write(path, report)
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))

    writer = RecordingWriter()
    runner, *_ = service(seed_module)
    runner.report_writer = writer
    report_path = tmp_path / "nested" / "report.json"

    result = runner.run(csv_path, report_path)

    assert len(snapshots) == 3
    assert [row["status"] for row in snapshots[0]["rows"]] == [
        "incomplete",
        "incomplete",
    ]
    assert [row["status"] for row in snapshots[1]["rows"]] == [
        "queued",
        "incomplete",
    ]
    assert [row["status"] for row in snapshots[2]["rows"]] == [
        "queued",
        "queued",
    ]
    assert snapshots[-1]["counts"] == {
        "duplicate": 0,
        "failed": 0,
        "queued": 2,
    }
    assert (
        report_path.read_text(encoding="utf-8")
        == json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    assert not list(report_path.parent.glob(".*.tmp"))


def test_failed_atomic_replace_preserves_previous_valid_report(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n",
    )
    replacements = 0

    def replace(source: os.PathLike[str], destination: os.PathLike[str]) -> None:
        nonlocal replacements
        replacements += 1
        if replacements == 2:
            raise OSError("simulated replacement failure")
        os.replace(source, destination)

    runner, *_ = service(seed_module)
    runner.report_writer = seed_module.AtomicReportWriter(replace=replace)
    report_path = tmp_path / "report.json"

    with pytest.raises(seed_module.SeedCommandError, match="report"):
        runner.run(csv_path, report_path)

    preserved = json.loads(report_path.read_text(encoding="utf-8"))
    assert preserved["rows"][0]["status"] == "incomplete"


def test_resume_skips_queued_and_duplicate_and_retries_failed_and_incomplete(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\n"
        "https://www.youtube.com/channel/UCalpha123\n"
        "https://www.youtube.com/channel/UCbeta1234\n"
        "https://www.youtube.com/channel/UCgamma123\n"
        "https://www.youtube.com/channel/UCdelta123\n",
    )
    report_path = tmp_path / "report.json"
    runner, *_ = service(seed_module)
    initial = runner.initialize_report(csv_path, report_path)
    initial.rows[0] = initial.rows[0].completed(status="queued", job_id=uuid4())
    initial.rows[1] = initial.rows[1].completed(status="duplicate")
    initial.rows[2] = initial.rows[2].completed(
        status="failed",
        error=seed_module.SeedRowError("seed_database_unavailable", "Try again."),
    )
    runner.report_writer.write(report_path, initial)

    resumed_store = Store(seed_module)
    resumed, _, _, dispatcher = service(seed_module, store=resumed_store)
    result = resumed.run(csv_path, report_path)

    assert [call[0] for call in resumed_store.calls] == [
        "UCgamma123",
        "UCdelta123",
    ]
    assert len(dispatcher.calls) == 2
    assert [row.status for row in result.rows] == [
        "queued",
        "duplicate",
        "queued",
        "queued",
    ]
    assert result.counts == {"queued": 3, "duplicate": 1, "failed": 0}


def test_changed_csv_rejects_existing_report_before_dependencies(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(
        tmp_path,
        "youtube_url\nhttps://www.youtube.com/channel/UCalpha123\n",
    )
    report_path = tmp_path / "report.json"
    runner, *_ = service(seed_module)
    runner.run(csv_path, report_path)
    csv_path.write_text(
        "youtube_url\nhttps://www.youtube.com/channel/UCbeta1234\n",
        encoding="utf-8",
    )
    resumed, store, resolver, dispatcher = service(seed_module)

    with pytest.raises(seed_module.SeedCommandError, match="different CSV"):
        resumed.run(csv_path, report_path)

    assert resolver.calls == []
    assert store.calls == []
    assert dispatcher.calls == []


def test_report_rows_correlate_input_and_have_bounded_safe_errors(
    seed_module, tmp_path
) -> None:
    csv_path = write_csv(tmp_path, "youtube_url,notes\ninvalid,Original note\n")
    runner, *_ = service(seed_module)

    result = runner.run(csv_path, tmp_path / "report.json")
    row = result.to_dict()["rows"][0]

    assert row["row_number"] == 2
    assert row["youtube_url"] == "invalid"
    assert row["notes"] == "Original note"
    assert row["status"] == "failed"
    assert set(result.counts) == {"queued", "duplicate", "failed"}
    assert len(row["error"]["code"]) <= 128
    assert len(row["error"]["message"]) <= 512
