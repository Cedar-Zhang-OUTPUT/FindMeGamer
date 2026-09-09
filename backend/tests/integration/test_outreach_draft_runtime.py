from datetime import timedelta
from uuid import UUID, uuid4
import httpx

from app.core.idempotency import utc_now
from app.db.models.outreach_drafts import OutreachDraft
from app.db.models.discovery import Activity
from app.db.models.profiles import GameProfile
from app.workers import outreach_draft_tasks as tasks
from tests.integration.test_outreach_drafts import (
    draft_setup,
    compose,
    get_compose,
    manual,
    values_for,
)
from tests.integration.test_activity_preparation import post
from tests.integration.test_discovery_evaluation import sessions_for
from tests.unit.outreach.test_draft_ai import gateway


def execute_fixture(session, calls, *, fail_name=None, during=None):
    def execute(data):
        calls.append(data["public_name"])
        if during:
            during(data)
        value = values_for({"input": data})
        if data["public_name"] == fail_name:
            value = httpx.ReadTimeout("do not expose this secret")
        ai, _ = gateway(value)
        return ai.generate(data)

    return lambda identity: tasks.run_draft(
        UUID(identity), session_factory=sessions_for(session), execute=execute
    )


def test_http_dispatch_worker_model_and_durable_read_preserve_partial_success(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(auth_client, session, monkeypatch)
    from app.workers.celery_app import celery_app

    queued = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: queued.append((name, args))
    )
    composition = compose(auth_client, activity, batch, template).json()
    assert len(queued) == 2 and all(
        name == "find_me_gamer.outreach.generate_draft" for name, _ in queued
    )
    calls = []
    run = execute_fixture(session, calls, fail_name="Creator 2")
    for _, args in queued:
        run(args[0])
    view = get_compose(auth_client, composition["id"])
    assert [d["status"] for d in view["drafts"]] == [
        "succeeded",
        "failed",
        "needs_repair",
    ]
    assert view["drafts"][1]["error_code"] == "draft_model_unavailable"
    assert "secret" not in str(view)
    assert view["drafts"][0]["rendered"]["fixed_hash"] == template["fixed_hash"]
    for _, args in queued:
        run(args[0])
    assert len(calls) == 2
    failed = view["drafts"][1]
    retried = post(
        auth_client,
        f"/api/v2/outreach/drafts/{failed['id']}/retry",
        {
            "expected_revision": failed["revision"],
            "context_token": failed["context_token"],
        },
    )
    assert retried.status_code == 200, retried.text
    execute_fixture(session, calls)(failed["id"])
    final = get_compose(auth_client, composition["id"])
    assert final["drafts"][0] == view["drafts"][0]
    assert final["drafts"][1]["status"] == "succeeded"
    assert calls == ["Creator 1", "Creator 2", "Creator 2"]


def test_broker_failure_replays_same_committed_composition(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    from app.workers.celery_app import celery_app

    def unavailable(*args, **kwargs):
        raise RuntimeError("broker secret")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    request_id, key = uuid4(), str(uuid4())
    failed = compose(
        auth_client, activity, batch, template, request_id=request_id, key=key
    )
    assert failed.status_code == 503, failed.text
    listed = auth_client.get(f"/api/v2/activities/{activity}/compositions").json()
    assert listed["total"] == 1
    queued = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: queued.append(args[0])
    )
    replay = compose(
        auth_client, activity, batch, template, request_id=request_id, key=key
    )
    assert replay.status_code == 201
    assert replay.json()["id"] == listed["items"][0]["id"]
    assert queued == [listed["items"][0]["drafts"][0]["id"]]


def test_late_generation_cannot_overwrite_human_edit(auth_client, session, monkeypatch):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    composition = compose(auth_client, activity, batch, template).json()
    identity = composition["drafts"][0]["id"]

    def human_edit(data):
        draft = get_compose(auth_client, composition["id"])["drafts"][0]
        response = manual(
            auth_client,
            draft,
            values_for(draft) | {"observation": "used silence before the reveal."},
        )
        assert response.status_code == 200, response.text

    execute_fixture(session, [], during=human_edit)(identity)
    final = get_compose(auth_client, composition["id"])["drafts"][0]
    assert final["values"]["observation"] == "used silence before the reveal."


def test_expired_running_is_unknown_without_automatic_second_model_call(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    composition = compose(auth_client, activity, batch, template).json()
    row = session.get(OutreachDraft, UUID(composition["drafts"][0]["id"]))
    row.status, row.lease_token, row.lease_expires_at = (
        "running",
        uuid4(),
        utc_now() - timedelta(seconds=1),
    )
    session.commit()
    calls = []
    execute_fixture(session, calls)(str(row.id))
    final = get_compose(auth_client, composition["id"])["drafts"][0]
    assert (
        not calls
        and final["status"] == "failed"
        and final["error_code"] == "draft_outcome_unknown"
    )


def test_expired_worker_is_visible_and_retryable_from_http_without_queue_redelivery(
    auth_client, session, monkeypatch
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    composition = compose(auth_client, activity, batch, template).json()
    row = session.get(OutreachDraft, UUID(composition["drafts"][0]["id"]))
    row.status, row.lease_token, row.lease_expires_at = (
        "running",
        uuid4(),
        utc_now() - timedelta(seconds=1),
    )
    session.commit()
    draft = get_compose(auth_client, composition["id"])["drafts"][0]
    assert (
        draft["status"] == "failed" and draft["error_code"] == "draft_outcome_unknown"
    )
    response = post(
        auth_client,
        f"/api/v2/outreach/drafts/{draft['id']}/retry",
        {
            "expected_revision": draft["revision"],
            "context_token": draft["context_token"],
        },
    )
    assert response.status_code == 200, response.text


def test_source_changes_before_or_during_generation_never_become_confirmed(
    auth_client, session, monkeypatch
):
    activity_id, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    composition = compose(auth_client, activity_id, batch, template).json()
    activity = session.get(Activity, UUID(activity_id))
    game = session.get(GameProfile, activity.game_id)

    def change(data):
        game.manual_overrides = game.manual_overrides | {
            "description": "New current description"
        }
        session.commit()

    calls = []
    execute_fixture(session, calls, during=change)(composition["drafts"][0]["id"])
    changed = get_compose(auth_client, composition["id"])["drafts"][0]
    assert changed["source_changed"] and not changed["sender_facts_valid"]
    template = post(auth_client, "/api/v2/outreach/template-versions/canonical", {"game_id": str(game.id)}).json()
    second = compose(auth_client, activity_id, batch, template).json()
    game.manual_overrides = game.manual_overrides | {"description": "Another change"}
    session.commit()
    execute_fixture(session, calls)(second["drafts"][0]["id"])
    assert len(calls) == 1
    assert (
        get_compose(auth_client, second["id"])["drafts"][0]["status"] == "needs_repair"
    )
