"""Real CLI processes, HTTP, PostgreSQL and per-mailbox Celery queues."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from mailbox_runtime_fixture import mailbox_runtime, until


def parallel(*actions):
    barrier = Barrier(len(actions))

    def invoke(action):
        barrier.wait(timeout=10)
        return action()

    with ThreadPoolExecutor(max_workers=len(actions)) as pool:
        return list(pool.map(invoke, actions))


def test_two_agents_separate_tokens(mailbox_runtime):
    r = mailbox_runtime
    a, b = parallel(lambda: r.create("a", "alpha"), lambda: r.create("b", "beta"))
    assert a["id"] != b["id"]
    assert (a["mailbox_id"], b["mailbox_id"]) == ("alpha", "beta")
    for agent, task in (("a", b), ("b", a)):
        for args in (
            ["outreach", "task", "get", task["id"]],
            [
                "outreach",
                "task",
                "start",
                task["id"],
                "--revision",
                task["revision"],
                "--confirm",
            ],
        ):
            result = r.run_cli(agent, args)
            assert result.returncode != 0
            assert r.error(result) in {
                "task_not_found",
                "outreach_task_not_found",
                "forbidden",
            }
    parallel(lambda: r.start("a", a), lambda: r.start("b", b))
    r.completed("a", a)
    r.completed("b", b)
    assert len(r.provider_calls("alpha")) == len(r.provider_calls("beta")) == 1


def test_two_agents_shared_token_same_key(mailbox_runtime):
    r = mailbox_runtime
    r.share_token()
    a, b = parallel(
        lambda: r.create("a", "alpha", key="same"),
        lambda: r.create("b", "alpha", key="same"),
    )
    assert a["id"] == b["id"]
    result = r.create("b", "beta", key="same", raw=True)
    assert result.returncode != 0
    assert r.error(result) == "idempotency_conflict"


def test_duplicate_start_and_send(mailbox_runtime):
    r = mailbox_runtime
    r.share_token()
    task = r.create("a", "alpha")
    parallel(lambda: r.start("a", task), lambda: r.start("b", task))
    rid = task["recipients"][0]["id"]
    for _ in range(3):
        r.publish("fmg_agent.outreach.send", rid, "alpha")
    r.completed("a", task)
    preview = task["recipients"][0]["preview_id"]
    results = parallel(
        *(lambda key=key: r.send("a", preview, key) for key in ("new-one", "new-two"))
    )
    assert all(r.error(result) == "preview_already_sent" for result in results)
    until(r.drained)
    assert len(r.provider_calls("alpha")) == 1
