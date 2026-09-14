from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import socket
import subprocess
import sys

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[3]
NOW = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)


def test_scheduler_module_is_import_safe_when_network_is_blocked() -> None:
    script = """
import socket

def blocked(*args, **kwargs):
    raise AssertionError("network access during scheduler import")

socket.create_connection = blocked
socket.socket.connect = blocked
import app.workers.schedules
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_beat_registers_stable_task_at_exact_fifteen_minute_cadence() -> None:
    from app.workers.celery_app import celery_app
    from app.workers.schedules import SCHEDULE_TASK_NAME, enqueue_due_reanalysis

    assert enqueue_due_reanalysis.name == SCHEDULE_TASK_NAME
    assert celery_app.tasks[SCHEDULE_TASK_NAME].name == SCHEDULE_TASK_NAME
    from app.matching.retention import MATCH_RETENTION_TASK_NAME

    assert celery_app.conf.beat_schedule == {
        "discover-recovery": {
            "task": "find_me_gamer.discover.sweep",
            "schedule": 30.0,
        },
        "mandatory-profile-reanalysis": {
            "task": SCHEDULE_TASK_NAME,
            "schedule": 900.0,
        },
        "match-input-retention": {
            "task": MATCH_RETENTION_TASK_NAME,
            "schedule": 3600.0,
        },
    }
    assert "app.matching.retention" in celery_app.conf.include
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]
    assert celery_app.conf.enable_utc is True
    assert celery_app.conf.task_acks_late is True


def test_beat_task_uses_default_batch_of_twenty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.workers.schedules import enqueue_due_reanalysis

    batches: list[int] = []

    class Service:
        def run(self, *, batch_size: int = 20) -> int:
            batches.append(batch_size)
            return 7

    monkeypatch.setattr(
        "app.workers.schedules.get_scheduled_reanalysis_service", Service
    )

    assert enqueue_due_reanalysis.apply(throw=True).get() == 7
    assert batches == [20]


@pytest.mark.parametrize("batch_size", [True, 0, 101, 1.5, "20"])
def test_invalid_direct_batch_is_rejected_before_service_construction(
    monkeypatch: pytest.MonkeyPatch, batch_size: object
) -> None:
    from app.workers.schedules import enqueue_due_reanalysis

    monkeypatch.setattr(
        "app.workers.schedules.get_scheduled_reanalysis_service",
        lambda: (_ for _ in ()).throw(AssertionError("service must not be built")),
    )

    with pytest.raises(ValueError, match="batch size"):
        enqueue_due_reanalysis.apply(args=[batch_size], throw=True)
