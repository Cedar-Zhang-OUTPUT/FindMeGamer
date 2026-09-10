"""Opt-in real Redis/Celery delivery with isolated PostgreSQL and synthetic I/O.

Run with FMG_RUN_BROKER_TEST=1 in compose.test.yaml. No production credentials,
provider/model network calls, SMTP, or existing frontend fixture mutation.
"""

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from threading import Event, Lock
import time
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.config import Config
from celery.contrib.testing.worker import start_worker
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.core.database import get_session
from app.core.idempotency import utc_now
from app.db.models.creator_search import CreatorSearchUnit
from app.db.models.profiles import CreatorProfile
from app.integrations.x_discovery import XDiscoveryGateway
from app.main import create_app
from app.schemas.discovery_plan_output import SearchPlanOutput
from app.workers import creator_search_tasks
from app.workers.celery_app import celery_app
from tests.integration.test_activity_api import activity, provider_page
from tests.integration.test_analyze_vertical_slice import AllowAllRateLimiter
from tests.integration.test_discovery_evaluation import fixture_executor

pytestmark = pytest.mark.skipif(
    os.environ.get("FMG_RUN_BROKER_TEST") != "1",
    reason="Requires the owned compose Redis test broker",
)


@dataclass
class Control:
    fail_last: bool = False
    hold: bool = False
    entered: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    lock: Lock = field(default_factory=Lock)
    profiles: Counter = field(default_factory=Counter)
    emails: Counter = field(default_factory=Counter)
    models: list = field(default_factory=list)
    deliveries: Counter = field(default_factory=Counter)
    redelivered: Event = field(default_factory=Event)


@pytest.fixture
def broker_search(database_engine, workspace_access_key, monkeypatch):
    database = "creator_search_broker_" + uuid4().hex
    with database_engine.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as admin:
        admin.execute(text(f'CREATE DATABASE "{database}"'))
    url = database_engine.url.set(database=database)
    engine = create_engine(url)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    control = Control()
    queue = "fmg-creator-search-test-" + uuid4().hex
    original_queue, original_routes = (
        celery_app.conf.task_default_queue,
        celery_app.conf.task_routes,
    )
    original_run = creator_search_tasks.run_creator_search

    @contextmanager
    def sessions():
        with factory() as session:
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise

    def profile(uid):
        with control.lock:
            control.profiles[str(uid)] += 1
        if control.hold:
            control.entered.set()
            assert control.release.wait(15), "Test must release the in-flight call"
        with sessions() as session:
            unit = session.get(CreatorSearchUnit, uid)
            if control.fail_last and unit.account_id == "3":
                raise RuntimeError("Synthetic one-Creator failure")
            row = session.get(CreatorProfile, unit.creator_id)
            row.analysis = {"summary": "Synthetic worker analysis."}
            row.last_analyzed_at = utc_now()
        return "ready"

    def email(uid):
        with control.lock:
            control.emails[str(uid)] += 1
        return "missing"

    @contextmanager
    def gateways(platform):
        with httpx.Client(
            transport=httpx.MockTransport(lambda req: provider_page([1, 2, 3]))
        ) as client:
            with XDiscoveryGateway(
                bearer_token="synthetic-only", http_client=client
            ) as gateway:
                yield gateway

    def generate(snapshot, conditions, model):
        return SearchPlanOutput.model_validate(
            {
                "summary": "Synthetic broker test.",
                "rationale": "Exercise actual task delivery.",
                "queries": [{"platform": "x", "terms": ["synthetic games"]}],
            }
        )

    def isolated_run(identity):
        with control.lock:
            control.deliveries[str(identity)] += 1
        result = original_run(
            identity,
            session_factory=sessions,
            plan_generator=generate,
            gateway_factory=gateways,
            profile_runner=profile,
            email_runner=email,
            execute_model=fixture_executor(control.models),
        )
        if control.deliveries[str(identity)] > 1:
            control.redelivered.set()
        return result

    try:
        config = Config("/app/alembic.ini")
        config.set_main_option(
            "sqlalchemy.url", url.render_as_string(hide_password=False)
        )
        with monkeypatch.context() as migration_env:
            migration_env.setenv(
                "DATABASE_URL", url.render_as_string(hide_password=False)
            )
            command.upgrade(config, "head")
        monkeypatch.setattr(creator_search_tasks, "run_creator_search", isolated_run)
        celery_app.conf.task_default_queue = queue
        celery_app.conf.update(
            task_routes={"find_me_gamer.creator_search.run": {"queue": queue}}
        )
        celery_app.amqp.flush_routes()
        celery_app.amqp.router = celery_app.amqp.Router()
        celery_app.loader.import_default_modules()
        app = create_app(rate_limiter=AllowAllRateLimiter())

        def api_sessions():
            with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = api_sessions
        with start_worker(
            celery_app,
            pool="solo",
            concurrency=1,
            queues=[queue],
            perform_ping_check=False,
            shutdown_timeout=15,
            loglevel="ERROR",
        ):
            with TestClient(
                app, headers={"Authorization": f"Bearer {workspace_access_key}"}
            ) as client:
                yield client, control
    finally:
        control.release.set()
        celery_app.conf.task_default_queue = original_queue
        celery_app.conf.update(task_routes=original_routes)
        with celery_app.connection_for_write() as connection:
            connection.channel().queue_delete(queue)
        engine.dispose()
        with database_engine.connect().execution_options(
            isolation_level="AUTOCOMMIT"
        ) as admin:
            admin.execute(text(f'DROP DATABASE "{database}"'))


def post(client, path, payload, key=None):
    response = client.post(
        path, json=payload, headers={"Idempotency-Key": key or uuid4().hex}
    )
    assert response.status_code == 202, response.text
    return response.json()


def start(client):
    campaign = activity(client)
    return post(
        client,
        f"/api/v2/activities/{campaign['id']}/creator-searches",
        {"mode": "discover", "platforms": ["x"]},
    )["search_id"]


def terminal(client, identity):
    for attempt in range(150):
        response = client.get("/api/v2/creator-searches/" + identity)
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in {"queued", "running", "stopping"}:
            return value
        time.sleep(0.1)
    raise AssertionError("Worker did not reach a terminal state within 15 seconds")


def test_real_broker_normal_and_duplicate_delivery_do_not_repeat_work(broker_search):
    client, control = broker_search
    identity = start(client)
    value = terminal(client, identity)
    assert value["status"] == "completed" and value["counts"]["matched"] == 3, value
    celery_app.send_task("find_me_gamer.creator_search.run", args=[identity])
    assert control.redelivered.wait(5), "Duplicate delivery must actually be consumed"
    assert sum(control.profiles.values()) == sum(control.emails.values()) == 3


def test_real_broker_partial_retry_keeps_successful_units_and_match_briefs(
    broker_search,
):
    client, control = broker_search
    control.fail_last = True
    identity = start(client)
    before = terminal(client, identity)
    assert before["status"] == "partial" and before["counts"]["matched"] == 2, before
    control.fail_last = False
    post(client, f"/api/v2/creator-searches/{identity}/retry", {})
    after = terminal(client, identity)
    assert after["status"] == "completed" and after["counts"]["matched"] == 3, after
    assert before["evaluation_id"] == after["evaluation_id"]
    assert sorted(control.profiles.values()) == [1, 1, 2]
    assert len([call for call in control.models if call[0] == "deep_match"]) == 3


def test_real_broker_stop_finishes_only_inflight_wave_then_explicit_retry(
    broker_search,
):
    client, control = broker_search
    control.hold = True
    identity = start(client)
    assert control.entered.wait(10)
    post(client, f"/api/v2/creator-searches/{identity}/stop", {})
    control.release.set()
    stopped = terminal(client, identity)
    assert stopped["status"] == "stopped"
    assert 1 <= stopped["counts"]["profile_ready"] <= 2
    assert stopped["evaluation_id"] is None and not control.emails
    assert sum(control.profiles.values()) <= 2
    control.hold = False
    post(client, f"/api/v2/creator-searches/{identity}/retry", {})
    complete = terminal(client, identity)
    assert (
        complete["status"] == "completed" and complete["counts"]["matched"] == 3
    ), complete
    assert sorted(control.profiles.values()) == [1, 1, 1]
