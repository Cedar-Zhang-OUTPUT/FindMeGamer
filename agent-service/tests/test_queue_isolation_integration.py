"""Required native PG/Redis gates: no skip fallback and no real upstream traffic."""

import json
import os
from pathlib import Path
import statistics
import subprocess
from threading import Event, Thread
import time

import pytest
from sqlalchemy import text

from mailbox_runtime_fixture import mailbox_runtime, until
from test_multi_agent_mailboxes import parallel


def test_four_blocked_enrichments_do_not_block_mail(mailbox_runtime):
    r = mailbox_runtime
    r.block_enrichment()
    jobs = r.enrich(4)
    until(lambda: r.redis.llen(r.prefix + "enrich_entered") == 4)
    assert len(set(r.redis.lrange(r.prefix + "enrich_entered", 0, -1))) == 4
    a, b = r.create("a", "alpha"), r.create("b", "beta")
    parallel(lambda: r.start("a", a), lambda: r.start("b", b))
    r.completed("a", a)
    r.completed("b", b)
    assert r.redis.exists(r.prefix + "block_enrichment")
    assert len(r.provider_calls("alpha")) == len(r.provider_calls("beta")) == 1
    r.release_enrichment()
    until(
        lambda: all(
            r.data(r.run_cli("a", ["email", "job", job]))["state"] == "completed"
            for job in jobs
        )
    )


def test_two_mailboxes_overlap(mailbox_runtime):
    r = mailbox_runtime
    r.redis.set(r.prefix + "block_mail", "1")
    a, b = r.create("a", "alpha"), r.create("b", "beta")
    parallel(lambda: r.start("a", a), lambda: r.start("b", b))
    until(
        lambda: all(
            r.redis.llen(r.prefix + "entered:" + name) == 1
            for name in ("alpha", "beta")
        )
    )
    assert r.provider_calls("alpha") == r.provider_calls("beta") == []
    r.redis.delete(r.prefix + "block_mail")
    r.completed("a", a)
    r.completed("b", b)
    ca, cb = r.provider_calls("alpha")[0], r.provider_calls("beta")[0]
    assert max(ca["start"], cb["start"]) < min(ca["end"], cb["end"])


@pytest.mark.parametrize("failure", ["429", "disabled", "bounce_protection"])
def test_a_failure_leaves_b_progressing(mailbox_runtime, failure):
    r = mailbox_runtime
    from fmg_agent.mail_runtime import set_runtime

    set_runtime(r.sessions, dispatch_enabled=False, send_enabled=True)
    a, b = r.create("a", "alpha", count=2), r.create("b", "beta", count=2)
    r.start("a", a)
    if failure == "429":
        r.redis.set(r.prefix + "mode:alpha", "429")
    elif failure == "disabled":
        r.profiles[0]["enabled"] = False
        r.save_profiles()
    else:
        from fmg_agent.email.safety import trip

        with r.sessions() as session:
            trip(session, "alpha@example.com", "bounce_retry_failures")
            session.commit()
    r.start("b", b)
    set_runtime(r.sessions, dispatch_enabled=True, send_enabled=True)
    r.completed("b", b)
    assert len(r.provider_calls("alpha")) == (1 if failure == "429" else 0)
    assert len(r.provider_calls("beta")) == 2
    assert r.get("a", a)["state"] != "completed"


def test_worker_loss_keeps_unknown_unreplayed(mailbox_runtime):
    r = mailbox_runtime
    r.redis.set(r.prefix + "mode:alpha", "crash")
    task = r.create("a", "alpha")
    r.start("a", task)
    until(lambda: len(r.provider_calls("alpha")) == 1)
    call = r.provider_calls("alpha")[0]
    # Advance only the durable stale timestamp; actual child dies after the
    # virtual provider accepts, before SendStore can persist its outcome.
    with r.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE email_sends SET updated_at = CURRENT_TIMESTAMP - INTERVAL '6 minutes' WHERE id=:id"
            ),
            {"id": call["id"]},
        )
    receipt = r.run_cli("a", ["email", "receipt", call["id"]])
    assert json.loads(receipt.stdout)["data"]["state"] == "unknown"
    # Remove the crash cooldown as a confounder: unknown's durable reservation
    # itself must prevent another upstream call, even once pacing permits one.
    with r.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE email_send_gates SET available_at=CURRENT_TIMESTAMP - INTERVAL '1 second', lease_id=NULL WHERE sender='alpha@example.com'"
            )
        )
    r.redis.delete(r.prefix + "mode:alpha")
    for _ in range(3):
        r.publish("fmg_agent.outreach.send", task["recipients"][0]["id"], "alpha")
    result = r.send("a", task["recipients"][0]["preview_id"], "different-key")
    assert r.error(result) == "preview_already_sent"
    # Prove the replacement pool consumes work, then wait for all duplicate
    # messages to leave both the ready queue and the broker's unacked ledger.
    marker = r.create("a", "alpha")
    r.start("a", marker)
    r.completed("a", marker)
    until(r.drained, 30)
    assert len(r.provider_calls("alpha")) == 2
    assert sum(c["id"] == call["id"] for c in r.provider_calls("alpha")) == 1


def test_real_roles_emit_fresh_local_readiness(mailbox_runtime):
    from fmg_agent.role_health import probe

    r = mailbox_runtime
    for role, mailbox in [
        ("enrichment", None),
        ("mail", "alpha"),
        ("mail", "beta"),
        ("dispatch", None),
        ("monitor", "alpha"),
        ("monitor", "beta"),
    ]:
        until(lambda: _ready(r.settings, role, mailbox), 30)
        evidence = probe(r.settings, role, mailbox)
        assert evidence["role"] == role
        assert evidence["mailbox"] == mailbox


def _ready(settings, role, mailbox):
    from fmg_agent.role_health import probe

    try:
        return probe(settings, role, mailbox)
    except (ValueError, OSError):
        return False


def test_old_expired_message_keeps_pending_recoverable(mailbox_runtime):
    r = mailbox_runtime
    from fmg_agent.mail_runtime import set_runtime

    set_runtime(r.sessions, dispatch_enabled=False, send_enabled=True)
    task = r.create("a", "alpha")
    r.start("a", task)
    r.publish(
        "fmg_agent.outreach.send", task["recipients"][0]["id"], "alpha", expires=-1
    )
    time.sleep(2)
    assert r.provider_calls("alpha") == []
    assert r.get("a", task)["stats"]["pending"] == 1
    set_runtime(r.sessions, dispatch_enabled=True, send_enabled=True)
    assert r.completed("a", task)["stats"]["sent"] == 1


def test_same_mailbox_combines_api_batch_and_retry_pacing(mailbox_runtime):
    r = mailbox_runtime
    from fmg_agent.email.inbox import ingest
    from test_bounce_safety import dsn

    from test_email_templates import variables

    source = r.directory / "direct-preview.json"
    source.write_text(
        json.dumps(
            {
                "mailbox_id": "alpha",
                "template_id": "game-outreach",
                "template_version": "5",
                "to": "direct@example.com",
                "variables": variables(),
            }
        )
    )
    preview = r.data(r.run_cli("a", ["email", "preview", "--input", str(source)]))["id"]
    first = r.data(r.send("a", preview, "direct"))
    detected = time.time()
    assert (
        ingest(
            r.sessions, "junk", "1", 1, dsn(first["id"], "pacing"), mailbox_id="alpha"
        )
        == "bounce"
    )
    batch = r.create("a", "alpha", count=2)
    r.start("a", batch)
    r.completed("a", batch)
    until(lambda: len(r.provider_calls("alpha")) == 4, 65)
    calls = sorted(r.provider_calls("alpha"), key=lambda c: c["start"])
    assert all(b["start"] >= a["end"] + 5 for a, b in zip(calls, calls[1:]))
    receipt = r.data(r.run_cli("a", ["email", "receipt", first["id"]]))
    retry_call = next(
        call for call in calls if call["id"] == receipt["bounce_retry"]["send_id"]
    )
    assert retry_call["start"] >= detected + 30


def test_resource_budget_baseline_and_slow_enrichment(mailbox_runtime):
    r = mailbox_runtime
    samples = []
    sampling_errors = []
    stop = Event()
    roots = {os.getpid(), *(p.pid for p in r.processes)}
    worker_parents = {p.pid for p in r.processes[1:4]}
    worker_children = {
        int(pid)
        for pid, parent in (
            line.split()
            for line in subprocess.check_output(
                ["ps", "-axo", "pid=,ppid="], text=True
            ).splitlines()
        )
        if int(parent) in worker_parents
    }
    assert len(worker_children) == 8
    # Include the dedicated native Redis/PostgreSQL servers and all their
    # children, in addition to API/dispatcher/monitor/Celery process trees.
    roots.add(int(r.redis.info("server")["process_id"]))
    with r.admin.connect() as conn:
        backend = conn.scalar(text("SELECT pg_backend_pid()"))
        roots.add(
            int(
                subprocess.check_output(
                    ["ps", "-p", str(backend), "-o", "ppid="], text=True
                ).strip()
            )
        )

    def collect_samples():
        while not stop.is_set():
            output = subprocess.check_output(
                ["ps", "-axo", "pid=,ppid=,rss=,%cpu="], text=True
            )
            rows = [line.split() for line in output.splitlines()]
            selected = set(roots)
            for _ in range(5):
                selected.update(
                    int(pid) for pid, parent, *_ in rows if int(parent) in selected
                )
            owned = [row for row in rows if int(row[0]) in selected]
            with r.admin.connect() as conn:
                connections = conn.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname='find_me_gamer_agent_test'"
                    )
                )
            samples.append(
                {
                    "rss_bytes": sum(int(row[2]) * 1024 for row in owned),
                    "cpu_percent": sum(float(row[3]) for row in owned),
                    "db_connections": connections,
                }
            )
            stop.wait(0.25)

    def sample():
        try:
            collect_samples()
        except Exception as exc:
            sampling_errors.append(repr(exc))

    thread = Thread(target=sample)
    thread.start()

    def scenario(dual):
        before = {name: len(r.provider_calls(name)) for name in ("alpha", "beta")}
        tasks = [("a", r.create("a", "alpha", count=10 if dual else 20))]
        if dual:
            tasks.append(("b", r.create("b", "beta", count=10)))
        start = time.time()
        for agent, task in tasks:
            r.start(agent, task)
        for agent, task in tasks:
            assert r.completed(agent, task, timeout=250)["stats"]["sent"] == (
                10 if dual else 20
            )
        calls = [c for name in before for c in r.provider_calls(name)[before[name] :]]
        assert len(calls) == len({c["id"] for c in calls}) == 20
        waits = sorted(c["start"] - start for c in calls)
        return {
            "messages": 20,
            "queue_wait_p95_seconds": waits[18],
            "elapsed_seconds": time.time() - start,
        }

    try:
        baseline = scenario(False)
        baseline_samples = len(samples)
        r.redis.set(r.prefix + "enrich_delay", "12")
        jobs = r.enrich(20)
        until(lambda: r.redis.llen(r.prefix + "enrich_entered") >= 4)
        dual = scenario(True)
        until(
            lambda: all(
                r.data(r.run_cli("a", ["email", "job", job]))["state"] == "completed"
                for job in jobs
            ),
            120,
        )
        until(r.drained)
        assert not sampling_errors, sampling_errors
        assert thread.is_alive()
        with r.admin.connect() as conn:
            max_connections = int(conn.scalar(text("SHOW max_connections")))
        for result, measurements in (
            (baseline, samples[:baseline_samples]),
            (dual, samples[baseline_samples:]),
        ):
            result.update(
                peak_rss_bytes=max(s["rss_bytes"] for s in measurements),
                peak_cpu_percent=max(s["cpu_percent"] for s in measurements),
                mean_cpu_percent=statistics.mean(
                    s["cpu_percent"] for s in measurements
                ),
                peak_db_connections=max(s["db_connections"] for s in measurements),
            )
        report = {
            "baseline": baseline,
            "dual_with_20_slow_enrichments": dual,
            "sample_interval_seconds": 0.25,
            "sample_count": len(samples),
            "max_connections": max_connections,
            "redis_version": r.redis.info("server")["redis_version"],
            "process_roots": sorted(roots),
            "enrichment_terminal_count": len(jobs),
            "broker_drained": r.drained(),
            "worker_children": sorted(worker_children),
        }
        path = Path(
            os.environ.get(
                "FMG_TASK7_RESOURCE_REPORT", str(r.directory / "resources.json")
            )
        )
        path.write_text(json.dumps(report, indent=2) + "\n")
        assert dual["queue_wait_p95_seconds"] <= baseline["queue_wait_p95_seconds"] + 10
        assert all(
            s["rss_bytes"] <= 2 * 1024**3
            and s["db_connections"] < max_connections * 0.7
            for s in samples
        )
        assert all(p.poll() is None for p in r.processes)
        for pid in worker_children:
            os.kill(pid, 0)
    finally:
        stop.set()
        thread.join(timeout=5)
