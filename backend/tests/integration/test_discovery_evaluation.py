from contextlib import contextmanager
import json
from uuid import UUID, uuid4

import httpx
import pytest


def seed_query(client, session, monkeypatch, count=2, token=None):
    from tests.integration.test_activity_api import (
        activity,
        query,
        execute,
        provider_page,
    )
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: None)
    launch = activity(client)
    accepted = query(
        client,
        launch["id"],
        providers=[{"platform": "x", "query": "indie", "page_size": 100}],
        batch_target=100,
    )
    execute(
        session,
        accepted["batch_id"],
        lambda request: provider_page(list(range(1, count + 1)), token=token),
    )
    return accepted["query_id"]


def test_evaluation_freezes_loaded_candidates_without_auto_selection(
    auth_client, session, monkeypatch
):
    query_id = seed_query(auth_client, session, monkeypatch)
    headers = {"Idempotency-Key": str(uuid4())}
    path = f"/api/v2/discovery/queries/{query_id}/evaluations"
    response = auth_client.post(path, headers=headers, json={})
    assert response.status_code == 202, response.text
    assert auth_client.post(path, headers=headers, json={}).json() == response.json()
    listed = auth_client.get(path).json()
    assert listed["total"] == 1
    run_id = response.json()["evaluation_id"]
    rows = auth_client.get(f"/api/v2/discovery/evaluations/{run_id}/results").json()
    assert rows["total"] == 2
    assert all(row["selected"] is False for row in rows["items"])
    assert all(row["status"] == "screening" for row in rows["items"])


def sessions_for(session):
    @contextmanager
    def sessions():
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise

    return sessions


def start(client, query_id, **payload):
    response = client.post(
        f"/api/v2/discovery/queries/{query_id}/evaluations",
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert response.status_code == 202, response.text
    return response.json()["evaluation_id"]


def read(client, identity):
    response = client.get(f"/api/v2/discovery/evaluations/{identity}")
    assert response.status_code == 200, response.text
    return response.json()


def results(client, identity):
    response = client.get(
        f"/api/v2/discovery/evaluations/{identity}/results", params={"limit": 200}
    )
    assert response.status_code == 200, response.text
    return response.json()["items"]


def fixture_executor(calls, *, fail_kind=None, fail_candidate=None, select_none=False):
    def execute(stage, payload):
        from app.discovery.evaluation_ai import EvaluationAI
        from app.integrations.deepseek import DeepSeekGateway
        from app.integrations.errors import TransientIntegrationError

        calls.append((stage, payload))
        if stage == fail_kind or (
            stage == "deep_match"
            and payload["candidate"]["candidate_id"] == fail_candidate
        ):
            raise TransientIntegrationError("synthetic fixture timeout")
        if stage == "screening":
            output = {
                "selected_ids": (
                    []
                    if select_none
                    else [c["candidate_id"] for c in payload["candidates"]]
                )
            }
        elif stage == "deep_match":
            candidate = payload["candidate"]
            output = {
                "candidate_id": candidate["candidate_id"],
                "summary": "Topic may suit this game.",
                "content_fit": "Existing metadata suggests a possible thematic connection.",
                "audience_fit": "Audience location and interests are unknown.",
                "limitations": [
                    "Only supplied records were considered; more evidence is needed."
                ],
                "cited_work_ids": [w["id"] for w in candidate["works"][:1]],
                "confidence": "limited",
            }
        else:
            output = {
                "items": [
                    {"candidate_id": b["candidate_id"], "score": 80 - index}
                    for index, b in enumerate(payload["briefs"])
                ]
            }

        def handler(request):
            assert request.url.path == "/chat/completions"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {"content": json.dumps(output)},
                        }
                    ]
                },
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with DeepSeekGateway(api_key="fixture-only", http_client=client) as gateway:
                ai = EvaluationAI(gateway)
                if stage == "screening":
                    return ai.screen(payload["game"], payload["candidates"])
                if stage == "deep_match":
                    return ai.deep(payload["game"], payload["candidate"])
                return ai.rank(payload["game"], payload["briefs"])

    return execute


def test_failed_deep_records_safe_diagnostic_but_preserves_public_contract(
    auth_client, session, monkeypatch, caplog
):
    from app.integrations.errors import InvalidModelOutput
    from app.workers.evaluation_tasks import run_evaluation, logger

    # Alembic fileConfig in preceding migration tests disables existing loggers.
    monkeypatch.setattr(logger, "disabled", False)

    identity = start(auth_client, seed_query(auth_client, session, monkeypatch))
    normal = fixture_executor([])

    def execute(kind, payload):
        if kind == "deep_match":
            raise InvalidModelOutput("evaluation_evidence_invalid")
        return normal(kind, payload)

    run_evaluation(identity, session_factory=sessions_for(session), execute_model=execute)
    events = [json.loads(record.getMessage()) for record in caplog.records
              if record.name == "app.workers.evaluation_tasks"]
    assert len(events) == 2
    assert all(event["reason"] == "evaluation_evidence_invalid" for event in events)
    assert all(event["run_id"] == identity for event in events)
    assert len({event["step_id"] for event in events}) == 2
    assert all(event["error_code"] == "evaluation_model_output_invalid" for event in events)
    assert read(auth_client, identity)["status"] == "failed"
    assert all(row["match_brief"] is None for row in results(auth_client, identity))


def test_progressive_http_model_worker_db_and_idempotent_delivery(
    auth_client, session, monkeypatch
):
    from app.workers.evaluation_tasks import run_evaluation

    query_id = seed_query(auth_client, session, monkeypatch)
    identity = start(auth_client, query_id)
    calls = []
    for _ in range(2):
        run_evaluation(
            identity,
            session_factory=sessions_for(session),
            execute_model=fixture_executor(calls),
        )
    state = read(auth_client, identity)
    assert state["status"] == "completed"
    assert state["candidate_count"] == state["matched_count"] == 2
    assert len(calls) == 4  # one screen, two deep calls, one ranking
    rows = results(auth_client, identity)
    assert all(row["status"] == "ranked" and row["match_brief"] for row in rows)
    assert all(row["evidence_status"] == "metadata_only" for row in rows)
    assert all(row["needs_enrichment"] and not row["sender_watched"] for row in rows)
    assert all(not row["selected"] and not row["stale"] for row in rows)
    assert all(
        not ({"score", "rank", "order", "ordinal", "input_order"} & set(row))
        for row in rows
    )
    assert state["usage"]["model_operations_started"] == 4


def test_hundred_candidates_are_chunked_without_old_thirty_cap(
    auth_client, session, monkeypatch
):
    from app.workers.evaluation_tasks import run_evaluation

    query_id = seed_query(auth_client, session, monkeypatch, count=100)
    identity = start(auth_client, query_id)
    calls = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(calls),
    )
    state = read(auth_client, identity)
    assert state["status"] == "completed"
    assert state["candidate_count"] == state["matched_count"] == 100
    screen = [p for stage, p in calls if stage == "screening"]
    ranks = [p for stage, p in calls if stage == "ranking"]
    assert len(screen) == len(ranks) == 5
    assert all(len(p["candidates"]) == 20 for p in screen)
    assert all(len(p["briefs"]) == 20 for p in ranks)
    assert len(results(auth_client, identity)) == 100


@pytest.mark.parametrize("failure", ["screening", "deep_match", "ranking"])
def test_failed_steps_do_not_become_no_matches_and_retry_only_failed(
    auth_client, session, monkeypatch, failure
):
    from app.workers.evaluation_tasks import run_evaluation

    identity = start(auth_client, seed_query(auth_client, session, monkeypatch))
    calls = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(calls, fail_kind=failure),
    )
    state = read(auth_client, identity)
    assert state["status"] == ("partial" if failure == "ranking" else "failed")
    assert state["retryable"]
    old_rows = results(auth_client, identity)
    if failure == "ranking":
        assert all(
            row["match_brief"] and row["fit_group"] == "unranked" for row in old_rows
        )
    old_succeeded = state["usage"]["succeeded_steps"]
    retry = auth_client.post(
        f"/api/v2/discovery/evaluations/{identity}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )
    assert retry.status_code == 202, retry.text
    later = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(later),
    )
    final = read(auth_client, identity)
    assert final["status"] == "completed"
    if failure == "ranking":
        assert [kind for kind, _ in later] == ["ranking"]
        assert {r["candidate_id"]: r["match_brief"] for r in old_rows} == {
            r["candidate_id"]: r["match_brief"] for r in results(auth_client, identity)
        }
    assert final["usage"]["succeeded_steps"] >= old_succeeded


def test_zero_screening_is_distinct_no_matches(auth_client, session, monkeypatch):
    from app.workers.evaluation_tasks import run_evaluation

    identity = start(auth_client, seed_query(auth_client, session, monkeypatch))
    calls = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(calls, select_none=True),
    )
    assert read(auth_client, identity)["status"] == "no_matches"
    assert len(calls) == 1
    assert all(
        row["status"] == "screened_out" for row in results(auth_client, identity)
    )


def test_one_failed_deep_retry_keeps_other_brief_and_score(
    auth_client, session, monkeypatch
):
    from app.workers.evaluation_tasks import run_evaluation

    identity = start(auth_client, seed_query(auth_client, session, monkeypatch))
    failed_id = results(auth_client, identity)[0]["candidate_id"]
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor([], fail_candidate=failed_id),
    )
    assert read(auth_client, identity)["status"] == "partial"
    good = next(
        r for r in results(auth_client, identity) if r["candidate_id"] != failed_id
    )
    assert good["status"] == "ranked"
    response = auth_client.post(
        f"/api/v2/discovery/evaluations/{identity}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )
    assert response.status_code == 202
    calls = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(calls),
    )
    assert read(auth_client, identity)["status"] == "completed"
    assert [kind for kind, _ in calls] == ["deep_match", "ranking"]
    assert (
        next(
            r for r in results(auth_client, identity) if r["candidate_id"] != failed_id
        )
        == good
    )


def test_expired_claim_rejects_late_publication_and_requires_explicit_retry(
    auth_client, session, monkeypatch
):
    from datetime import timedelta
    from app.core.idempotency import utc_now
    from app.db.models.discovery_evaluation import EvaluationStep
    from app.workers.evaluation_tasks import _claims, _publish, run_evaluation

    identity = start(auth_client, seed_query(auth_client, session, monkeypatch))
    with sessions_for(session)() as db:
        claim = _claims(db, UUID(identity))[0]
    assert _claims(session, UUID(identity)) == []  # duplicate delivery cannot claim it
    response = auth_client.post(
        f"/api/v2/discovery/evaluations/{identity}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )
    assert response.status_code == 409
    step = session.get(EvaluationStep, claim[0])
    step.lease_expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    old_output = fixture_executor([])(claim[2], claim[3])
    with sessions_for(session)() as db:
        _publish(db, UUID(identity), claim, old_output, None)
    assert read(auth_client, identity)["usage"]["succeeded_steps"] == 0
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor([]),
    )
    assert read(auth_client, identity)["status"] == "failed"
    response = auth_client.post(
        f"/api/v2/discovery/evaluations/{identity}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )
    assert response.status_code == 202
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor([]),
    )
    assert read(auth_client, identity)["status"] == "completed"
    with sessions_for(session)() as db:
        _publish(db, UUID(identity), claim, old_output, None)
    assert read(auth_client, identity)["usage"]["model_operations_started"] == 5


@pytest.mark.parametrize("change", ["creator", "game", "work", "identity"])
def test_effective_changes_mark_frozen_results_stale_without_rewriting_brief(
    auth_client, session, monkeypatch, change
):
    from app.db.models.profiles import CreatorProfile, GameProfile
    from app.workers.evaluation_tasks import run_evaluation

    identity = start(auth_client, seed_query(auth_client, session, monkeypatch))
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor([]),
    )
    before = results(auth_client, identity)[0]
    creator = session.get(CreatorProfile, UUID(before["creator_id"]))
    if change == "creator":
        creator.manual_overrides = {"description": "Changed content direction"}
        creator.manual_revision += 1
    elif change == "identity":
        creator.platform_account_id = "new-account"
        creator.identity_revision += 1
    elif change == "work":
        creator.works[0].manual_overrides = {"verification_notes": "New source note"}
    else:
        game = session.get(
            GameProfile,
            UUID(read(auth_client, identity)["source_snapshot"]["game"]["id"]),
        )
        game.manual_overrides = {"description": "Changed game direction"}
    session.commit()
    after = next(
        r
        for r in results(auth_client, identity)
        if r["candidate_id"] == before["candidate_id"]
    )
    assert after["stale"]
    assert after["identity_changed"] == (change == "identity")
    assert after["match_brief"] == before["match_brief"]
    assert after["account_id"] == before["account_id"]
    assert not after["sender_watched"] and not after["selected"]


def test_rebound_before_creation_never_evaluates_new_account(
    auth_client, session, monkeypatch
):
    from sqlalchemy import select
    from app.db.models.discovery import DiscoveryCandidate
    from app.db.models.profiles import CreatorProfile
    from app.workers.evaluation_tasks import run_evaluation

    query_id = seed_query(auth_client, session, monkeypatch, count=1)
    candidate = session.scalar(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == UUID(query_id))
    )
    creator = session.get(CreatorProfile, candidate.creator_id)
    creator.identity_revision += 1
    creator.platform_account_id = "new-account"
    session.commit()
    identity = start(auth_client, query_id)
    calls = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(calls),
    )
    assert not calls
    assert read(auth_client, identity)["status"] == "failed"
    row = results(auth_client, identity)[0]
    assert row["identity_changed"] and row["match_brief"] is None
    assert row["account_id"] != "new-account"


def test_saved_run_replays_after_broker_failure(auth_client, session, monkeypatch):
    from app.workers.celery_app import celery_app

    query_id = seed_query(auth_client, session, monkeypatch)
    path = f"/api/v2/discovery/queries/{query_id}/evaluations"
    headers = {"Idempotency-Key": str(uuid4())}

    def unavailable(*args, **kwargs):
        raise RuntimeError("private-broker-value")

    monkeypatch.setattr(celery_app, "send_task", unavailable)
    failed = auth_client.post(path, headers=headers, json={})
    assert failed.status_code == 503 and "private-broker-value" not in failed.text
    monkeypatch.setattr(celery_app, "send_task", lambda *args, **kwargs: None)
    replay = auth_client.post(path, headers=headers, json={})
    assert replay.status_code == 202
    assert auth_client.get(path).json()["total"] == 1


def test_evaluation_rejects_foreign_members_and_empty_selection(
    auth_client, session, monkeypatch
):
    query_id = seed_query(auth_client, session, monkeypatch)
    for ids in ([], [str(uuid4())]):
        response = auth_client.post(
            f"/api/v2/discovery/queries/{query_id}/evaluations",
            headers={"Idempotency-Key": str(uuid4())},
            json={"candidate_ids": ids},
        )
        assert response.status_code == 422


def test_membership_does_not_expand_when_discovery_continues(
    auth_client, session, monkeypatch
):
    from tests.integration.test_activity_api import execute, provider_page

    query_id = seed_query(auth_client, session, monkeypatch, token="next-page")
    identity = start(auth_client, query_id)
    response = auth_client.post(
        f"/api/v2/discovery/queries/{query_id}/continue",
        headers={"Idempotency-Key": str(uuid4())},
        json={},
    )
    assert response.status_code == 202, response.text
    execute(session, response.json()["batch_id"], lambda request: provider_page([3, 4]))
    assert (
        auth_client.get(f"/api/v2/discovery/queries/{query_id}/results").json()["total"]
        == 4
    )
    assert len(results(auth_client, identity)) == 2


def test_recorded_evidence_keeps_known_source_but_never_confirms_sender(
    auth_client, session, monkeypatch
):
    from sqlalchemy import select
    from app.db.models.discovery import DiscoveryCandidate, DiscoveryQuery
    from app.db.models.profiles import CreatorProfile
    from app.workers.evaluation_tasks import run_evaluation

    query_id = seed_query(auth_client, session, monkeypatch, count=1)
    candidate = session.scalar(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == UUID(query_id))
    )
    creator = session.get(CreatorProfile, candidate.creator_id)
    game_id = session.get(DiscoveryQuery, UUID(query_id)).source_snapshot["game"]["id"]
    work = creator.works[0]
    work.manual_overrides = {
        "evidence_excerpt": "Recorded discussion of cooperative puzzle mechanics.",
        "verification_notes": "Editor checked this source.",
        "game_id": game_id,
        "timestamp_seconds": 42,
    }
    session.commit()
    identity = start(auth_client, query_id)
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor([]),
    )
    row = results(auth_client, identity)[0]
    assert row["evidence_status"] == "recorded_evidence"
    assert row["evidence"][0]["work_id"] == str(work.id)
    assert row["evidence"][0]["relation"] == "current_game"
    assert row["evidence"][0]["timestamp_seconds"] == 42
    assert not row["sender_watched"]


def test_claim_limit_and_resume_after_published_screen(
    auth_client, session, monkeypatch
):
    from app.workers.evaluation_tasks import _claims, _publish, run_evaluation

    identity = start(
        auth_client, seed_query(auth_client, session, monkeypatch, count=100)
    )
    with sessions_for(session)() as db:
        claims = _claims(db, UUID(identity))
    assert len(claims) == 4
    assert _claims(session, UUID(identity)) == []
    for claim in claims:
        output = fixture_executor([])(claim[2], claim[3])
        with sessions_for(session)() as db:
            _publish(db, UUID(identity), claim, output, None)
    calls = []
    run_evaluation(
        identity,
        session_factory=sessions_for(session),
        execute_model=fixture_executor(calls),
    )
    assert read(auth_client, identity)["status"] == "completed"
    assert sum(kind == "screening" for kind, _ in calls) == 1


def test_evaluation_routes_require_workspace_auth(auth_client, session, monkeypatch):
    query_id = seed_query(auth_client, session, monkeypatch)
    identity = start(auth_client, query_id)
    for method, path in (
        ("get", f"/api/v2/discovery/queries/{query_id}/evaluations"),
        ("post", f"/api/v2/discovery/queries/{query_id}/evaluations"),
        ("get", f"/api/v2/discovery/evaluations/{identity}"),
        ("get", f"/api/v2/discovery/evaluations/{identity}/results"),
        ("post", f"/api/v2/discovery/evaluations/{identity}/retry"),
    ):
        response = auth_client.request(
            method,
            path,
            headers={"Authorization": "Bearer wrong", "Idempotency-Key": str(uuid4())},
            **({"json": {}} if method == "post" else {}),
        )
        assert response.status_code == 401


def test_evaluation_brief_has_typed_client_contract(auth_client):
    schema = auth_client.app.openapi()
    field = schema["components"]["schemas"]["EvaluationResult"]["properties"][
        "match_brief"
    ]
    assert {"$ref": "#/components/schemas/EvaluationMatchBrief"} in field["anyOf"]
