from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session

from app.core.crypto import SecretCipher
from app.core.database import get_session
from app.core.security import hash_workspace_key
from app.db.models.idempotency import IdempotencyRecord
from app.db.models.match import MatchTask
from app.db.models.outreach import (
    Delivery,
    OutreachCampaign,
    SendBatch,
    Template,
)
from app.db.models.profiles import CreatorProfile, GameProfile
from app.main import create_app


TEMPLATE_PATH = "/api/v1/outreach/templates"
TEMPLATE_PAYLOAD = {
    "name": "Creator launch",
    "subject_template": "An invitation for {{creator_name}}",
    "body_markdown": "Hello {{creator_name}} from {{sender_name}}.",
    "accepted_label": "Count me in",
    "declined_label": "Not this time",
}
ERROR_MESSAGES = {
    "workspace_key_invalid": "A valid Workspace Access Key is required.",
    "template_not_found": "The requested Template was not found.",
    "template_name_conflict": "A Template with that name already exists.",
    "template_last_remaining": "The only remaining Template cannot be deleted.",
    "template_default_delete_forbidden": (
        "Select another default Template before deleting this one."
    ),
}


def _create(client: TestClient, **overrides: object):
    payload = {**TEMPLATE_PAYLOAD, **overrides}
    return client.post(TEMPLATE_PATH, json=payload)


def _assert_error(response, *, status: int, code: str) -> None:
    assert response.status_code == status
    assert response.json() == {
        "error": {
            "code": code,
            "message": ERROR_MESSAGES[code],
            "retryable": False,
            "correlation_id": response.headers["x-correlation-id"],
        }
    }


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", TEMPLATE_PATH, None),
        ("post", TEMPLATE_PATH, TEMPLATE_PAYLOAD),
        ("get", f"{TEMPLATE_PATH}/00000000-0000-4000-8000-000000000001", None),
        (
            "patch",
            f"{TEMPLATE_PATH}/00000000-0000-4000-8000-000000000001",
            {"name": "Changed"},
        ),
        (
            "delete",
            f"{TEMPLATE_PATH}/00000000-0000-4000-8000-000000000001",
            None,
        ),
        (
            "post",
            f"{TEMPLATE_PATH}/00000000-0000-4000-8000-000000000001/duplicate",
            None,
        ),
        (
            "post",
            f"{TEMPLATE_PATH}/00000000-0000-4000-8000-000000000001/default",
            None,
        ),
        (
            "post",
            f"{TEMPLATE_PATH}/00000000-0000-4000-8000-000000000001/preview",
            {},
        ),
    ],
)
def test_all_template_routes_require_workspace_authentication(
    client, method: str, path: str, payload: dict[str, object] | None
) -> None:
    request = getattr(client, method)
    response = request(path, **({"json": payload} if payload is not None else {}))

    _assert_error(response, status=401, code="workspace_key_invalid")


def test_create_list_and_detail_have_stable_shared_contract(auth_client) -> None:
    first = _create(auth_client, name="  Zebra launch  ")
    second = _create(auth_client, name="alpha launch")
    third = _create(auth_client, name="Beta launch")

    assert [first.status_code, second.status_code, third.status_code] == [201, 201, 201]
    assert first.json()["name"] == "Zebra launch"
    assert first.json()["version"] == 1
    assert first.json()["is_default"] is True
    assert second.json()["is_default"] is False
    assert third.json()["is_default"] is False
    assert set(first.json()) == {
        "id",
        "name",
        "version",
        "subject_template",
        "body_markdown",
        "accepted_label",
        "declined_label",
        "is_default",
        "created_at",
        "updated_at",
    }
    assert datetime.fromisoformat(first.json()["created_at"])
    assert datetime.fromisoformat(first.json()["updated_at"])

    listed = auth_client.get(TEMPLATE_PATH)
    detail = auth_client.get(f"{TEMPLATE_PATH}/{second.json()['id']}")

    assert listed.status_code == 200
    assert [item["name"] for item in listed.json()["items"]] == [
        "Zebra launch",
        "alpha launch",
        "Beta launch",
    ]
    assert detail.status_code == 200
    assert detail.json() == second.json()


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"subject_template": "Hello {{unknown_name}}"}, "template_invalid"),
        ({"body_markdown": "Hello { creator_name }"}, "template_invalid"),
        (
            {"subject_template": "Hello\r\nBcc: victim@example.com"},
            "template_invalid",
        ),
        ({"accepted_label": "   "}, "request_invalid"),
        ({"declined_label": "No\x00thanks"}, "request_invalid"),
        ({"subject_template": "\t\n"}, "request_invalid"),
        ({"body_markdown": " \r\n "}, "request_invalid"),
    ],
)
def test_create_rejects_invalid_render_content_atomically(
    auth_client,
    session: Session,
    overrides: dict[str, object],
    error_code: str,
) -> None:
    response = _create(auth_client, **overrides)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code
    assert session.scalar(select(func.count()).select_from(Template)) == 0
    assert "victim@example.com" not in response.text


def test_create_defaults_labels_and_rejects_protected_or_extra_fields(
    auth_client,
) -> None:
    payload = {
        "name": "Defaults",
        "subject_template": "Hello",
        "body_markdown": "Body",
    }
    created = auth_client.post(TEMPLATE_PATH, json=payload)

    assert created.status_code == 201
    assert created.json()["accepted_label"] == "Yes, I'm in"
    assert created.json()["declined_label"] == "No, I'm not interested"

    for protected in ("id", "version", "is_default", "created_at", "unknown"):
        rejected = auth_client.post(TEMPLATE_PATH, json={**payload, protected: 2})
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "request_invalid"


def test_patch_preserves_author_text_and_increments_once(auth_client) -> None:
    created = _create(auth_client)
    template_id = created.json()["id"]
    subject = "  Hello {{creator_name}}  "
    markdown = "\n  Dear {{creator_name}},\n\n*Welcome.*  \n"

    updated = auth_client.patch(
        f"{TEMPLATE_PATH}/{template_id}",
        json={"subject_template": subject, "body_markdown": markdown},
    )
    reread = auth_client.get(f"{TEMPLATE_PATH}/{template_id}")

    assert updated.status_code == 200
    assert updated.json()["subject_template"] == subject
    assert updated.json()["body_markdown"] == markdown
    assert updated.json()["version"] == 2
    assert reread.json() == updated.json()


def test_patch_noop_does_not_increment_or_change_timestamp(auth_client) -> None:
    created = _create(auth_client)
    template_id = created.json()["id"]

    noop = auth_client.patch(
        f"{TEMPLATE_PATH}/{template_id}",
        json={
            "name": created.json()["name"],
            "subject_template": created.json()["subject_template"],
            "body_markdown": created.json()["body_markdown"],
            "accepted_label": created.json()["accepted_label"],
            "declined_label": created.json()["declined_label"],
        },
    )

    assert noop.status_code == 200
    assert noop.json() == created.json()


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"subject_template": None}])
def test_patch_rejects_empty_or_explicit_null_payload(
    auth_client, payload: dict[str, object]
) -> None:
    created = _create(auth_client)

    response = auth_client.patch(
        f"{TEMPLATE_PATH}/{created.json()['id']}", json=payload
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_invalid"
    assert (
        auth_client.get(f"{TEMPLATE_PATH}/{created.json()['id']}").json()
        == created.json()
    )


def test_invalid_patch_rolls_back_without_version_or_content_change(
    auth_client,
) -> None:
    created = _create(auth_client)
    template_id = created.json()["id"]

    response = auth_client.patch(
        f"{TEMPLATE_PATH}/{template_id}",
        json={"subject_template": "Hello\nBcc: private@example.com"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "template_invalid"
    assert "private@example.com" not in response.text
    assert auth_client.get(f"{TEMPLATE_PATH}/{template_id}").json() == created.json()


def test_names_are_trimmed_and_case_insensitively_unique_on_create_and_edit(
    auth_client,
) -> None:
    first = _create(auth_client, name="  Partner Pitch  ")
    conflict = _create(auth_client, name="partner pitch")
    second = _create(auth_client, name="Other Pitch")
    edit_conflict = auth_client.patch(
        f"{TEMPLATE_PATH}/{second.json()['id']}", json={"name": " PARTNER PITCH "}
    )

    assert first.status_code == 201
    _assert_error(conflict, status=409, code="template_name_conflict")
    _assert_error(edit_conflict, status=409, code="template_name_conflict")
    listed = auth_client.get(TEMPLATE_PATH).json()["items"]
    assert [(item["name"], item["version"]) for item in listed] == [
        ("Partner Pitch", 1),
        ("Other Pitch", 1),
    ]


def test_duplicate_copies_content_and_chooses_first_available_name(auth_client) -> None:
    source = _create(auth_client, name="Pitch")
    occupied = _create(auth_client, name="pitch copy")
    first_copy = auth_client.post(f"{TEMPLATE_PATH}/{source.json()['id']}/duplicate")
    second_copy = auth_client.post(f"{TEMPLATE_PATH}/{source.json()['id']}/duplicate")

    assert occupied.status_code == 201
    assert first_copy.status_code == 201
    assert second_copy.status_code == 201
    assert first_copy.json()["name"] == "Pitch Copy 2"
    assert second_copy.json()["name"] == "Pitch Copy 3"
    for duplicate in (first_copy.json(), second_copy.json()):
        assert duplicate["version"] == 1
        assert duplicate["is_default"] is False
        for field in (
            "subject_template",
            "body_markdown",
            "accepted_label",
            "declined_label",
        ):
            assert duplicate[field] == source.json()[field]


def test_duplicate_name_stays_within_column_limit(auth_client) -> None:
    source = _create(auth_client, name="N" * 255)

    duplicate = auth_client.post(f"{TEMPLATE_PATH}/{source.json()['id']}/duplicate")

    assert duplicate.status_code == 201
    assert len(duplicate.json()["name"]) == 255
    assert duplicate.json()["name"].endswith(" Copy")


def test_setting_default_is_atomic_content_version_noop(auth_client) -> None:
    first = _create(auth_client, name="First")
    second = _create(auth_client, name="Second")

    selected = auth_client.post(f"{TEMPLATE_PATH}/{second.json()['id']}/default")
    repeated = auth_client.post(f"{TEMPLATE_PATH}/{second.json()['id']}/default")
    items = auth_client.get(TEMPLATE_PATH).json()["items"]

    assert selected.status_code == 200
    assert repeated.status_code == 200
    assert selected.json()["version"] == second.json()["version"] == 1
    assert repeated.json()["version"] == 1
    assert [item["id"] for item in items if item["is_default"]] == [second.json()["id"]]
    assert (
        next(item for item in items if item["id"] == first.json()["id"])["is_default"]
        is False
    )


def test_delete_rejects_last_and_current_default_then_deletes_eligible_row(
    auth_client,
) -> None:
    first = _create(auth_client, name="First")
    only = auth_client.delete(f"{TEMPLATE_PATH}/{first.json()['id']}")
    second = _create(auth_client, name="Second")
    current_default = auth_client.delete(f"{TEMPLATE_PATH}/{first.json()['id']}")
    auth_client.post(f"{TEMPLATE_PATH}/{second.json()['id']}/default")
    deleted = auth_client.delete(f"{TEMPLATE_PATH}/{first.json()['id']}")

    _assert_error(only, status=409, code="template_last_remaining")
    _assert_error(current_default, status=409, code="template_default_delete_forbidden")
    assert deleted.status_code == 204
    assert deleted.content == b""
    listed = auth_client.get(TEMPLATE_PATH).json()["items"]
    assert [(item["id"], item["is_default"]) for item in listed] == [
        (second.json()["id"], True)
    ]


def _delivery_snapshot(
    session: Session, template: Template
) -> tuple[UUID, dict[str, object]]:
    now = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    game = GameProfile(
        steam_app_id=str(uuid4().int % 10**16),
        canonical_url="https://store.steampowered.com/app/10",
        sort_name="Snapshot Game",
    )
    creator = CreatorProfile(
        youtube_channel_id=f"UC{uuid4().hex[:22]}",
        canonical_url="https://youtube.com/channel/snapshot",
        sort_name="Snapshot Creator",
    )
    session.add_all([game, creator])
    session.flush()
    match_task = MatchTask(
        game_id=game.id,
        shuffle_seed=1,
        recommended_match_threshold=Decimal("0.7000"),
        input_expires_at=now + timedelta(days=30),
    )
    session.add(match_task)
    session.flush()
    campaign = OutreachCampaign(match_task_id=match_task.id)
    session.add(campaign)
    session.flush()
    batch = SendBatch(
        campaign_id=campaign.id,
        template_id=template.id,
        requested_creator_ids=[str(creator.id)],
    )
    session.add(batch)
    session.flush()
    snapshot = {
        "rendered_subject": "Historical subject",
        "rendered_markdown": "Historical markdown",
        "rendered_html": "<p>Historical HTML</p>",
        "template_name": template.name,
        "template_version": template.version,
        "accepted_label": "Historical yes",
        "declined_label": "Historical no",
    }
    delivery = Delivery(
        campaign_id=campaign.id,
        send_batch_id=batch.id,
        creator_id=creator.id,
        recipient_email="snapshot@example.com",
        **snapshot,
        sender_name="Historical sender",
        sender_address="sender@example.com",
        reply_to="reply@example.com",
        response_token_digest=sha256(uuid4().bytes).hexdigest(),
    )
    session.add(delivery)
    session.flush()
    return batch.id, {**snapshot, "id": delivery.id}


def test_deleting_template_detaches_batch_without_mutating_delivery_history(
    auth_client, session: Session
) -> None:
    first = _create(auth_client, name="Default")
    historical = _create(auth_client, name="Historical")
    row = session.get(Template, UUID(historical.json()["id"]))
    assert row is not None
    batch_id, snapshot = _delivery_snapshot(session, row)

    response = auth_client.delete(f"{TEMPLATE_PATH}/{historical.json()['id']}")
    session.expire_all()
    batch = session.get(SendBatch, batch_id)
    delivery = session.get(Delivery, snapshot.pop("id"))

    assert first.json()["is_default"] is True
    assert response.status_code == 204
    assert batch is not None and batch.template_id is None
    assert delivery is not None
    assert {field: getattr(delivery, field) for field in snapshot} == snapshot


def test_preview_uses_fixed_sample_and_unsaved_draft_without_side_effects(
    auth_client, session: Session, workspace_access_key: str
) -> None:
    created = _create(
        auth_client,
        subject_template="Persisted subject",
        body_markdown="Persisted body",
    )
    template_id = created.json()["id"]
    tracked_models = (
        Template,
        OutreachCampaign,
        SendBatch,
        Delivery,
        IdempotencyRecord,
    )
    before = {
        model: session.scalar(select(func.count()).select_from(model))
        for model in tracked_models
    }

    response = auth_client.post(
        f"{TEMPLATE_PATH}/{template_id}/preview",
        json={
            "subject_template": "{{creator_name}} / {{channel_name}} / {{game_name}}",
            "body_markdown": (
                "{{steam_url}}\n\n{{game_summary}}\n\n{{match_reason}}\n\n"
                "{{sender_name}}\n\n<script>unsafe()</script>"
            ),
            "accepted_label": "<Preview yes>",
            "declined_label": "Preview no",
        },
    )
    after = {
        model: session.scalar(select(func.count()).select_from(model))
        for model in tracked_models
    }

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == "Sample Creator / Sample Channel / Sample Game"
    for value in (
        "https://store.steampowered.com/app/000000",
        "Sample Sender",
        "https://example.invalid/r/preview-accepted",
        "https://example.invalid/r/preview-declined",
    ):
        assert value in body["html"]
    assert "<script>" not in body["html"]
    assert "&lt;Preview yes&gt;" in body["html"]
    assert "Persisted subject" not in response.text
    assert workspace_access_key not in response.text
    assert "__FIND_ME_GAMER_" not in response.text
    assert before == after
    assert auth_client.get(f"{TEMPLATE_PATH}/{template_id}").json() == created.json()


def test_preview_without_draft_uses_persisted_template(auth_client) -> None:
    created = _create(
        auth_client,
        subject_template="Hello {{creator_name}}",
        body_markdown="For {{game_name}}: {{match_reason}}",
    )

    response = auth_client.post(f"{TEMPLATE_PATH}/{created.json()['id']}/preview")

    assert response.status_code == 200
    assert response.json()["subject"] == "Hello Sample Creator"
    assert "Sample Game" in response.json()["markdown"]
    assert "example.invalid" in response.json()["html"]


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"subject_template": None}, "request_invalid"),
        ({"body_markdown": "{{secret}}"}, "template_invalid"),
        ({"accepted_label": "\n"}, "request_invalid"),
        ({"name": "not-a-preview-field"}, "request_invalid"),
    ],
)
def test_invalid_preview_draft_is_safe_and_unsaved(
    auth_client, payload: dict[str, object], error_code: str
) -> None:
    created = _create(auth_client)
    response = auth_client.post(
        f"{TEMPLATE_PATH}/{created.json()['id']}/preview", json=payload
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == error_code
    assert (
        auth_client.get(f"{TEMPLATE_PATH}/{created.json()['id']}").json()
        == created.json()
    )


@pytest.mark.parametrize(
    ("method", "suffix", "payload"),
    [
        ("get", "", None),
        ("patch", "", {"name": "Missing"}),
        ("delete", "", None),
        ("post", "/duplicate", None),
        ("post", "/default", None),
        ("post", "/preview", {}),
    ],
)
def test_missing_template_uses_stable_safe_error(
    auth_client, method: str, suffix: str, payload: dict[str, object] | None
) -> None:
    missing = uuid4()
    request = getattr(auth_client, method)
    response = request(
        f"{TEMPLATE_PATH}/{missing}{suffix}",
        **({"json": payload} if payload is not None else {}),
    )

    _assert_error(response, status=404, code="template_not_found")
    assert str(missing) not in response.text


class AlwaysAllow:
    def allow(self, workspace_digest: str, client_address: str) -> bool:
        return True


@pytest.fixture
def independent_template_clients(
    migrated_database: None,
    database_engine: Engine,
    workspace_access_key: str,
) -> Iterator[tuple[TestClient, TestClient, Engine]]:
    with Session(database_engine) as cleanup, cleanup.begin():
        cleanup.execute(delete(Template))

    app = create_app(
        workspace_key_hash=hash_workspace_key(workspace_access_key),
        rate_limiter=AlwaysAllow(),
        secret_cipher=SecretCipher(bytes(range(32))),
    )

    def independent_session() -> Iterator[Session]:
        with Session(database_engine) as database_session:
            try:
                yield database_session
                database_session.commit()
            except Exception:
                database_session.rollback()
                raise

    app.dependency_overrides[get_session] = independent_session
    headers = {"Authorization": f"Bearer {workspace_access_key}"}
    try:
        with TestClient(app, headers=headers) as first:
            with TestClient(app, headers=headers) as second:
                yield first, second, database_engine
    finally:
        app.dependency_overrides.clear()
        with Session(database_engine) as cleanup, cleanup.begin():
            cleanup.execute(delete(Template))


def test_concurrent_first_creates_preserve_one_default(
    independent_template_clients: tuple[TestClient, TestClient, Engine],
) -> None:
    first, second, engine = independent_template_clients
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = [
            future.result(timeout=10)
            for future in (
                executor.submit(_create, first, name="Concurrent A"),
                executor.submit(_create, second, name="Concurrent B"),
            )
        ]

    assert sorted(response.status_code for response in responses) == [201, 201]
    with Session(engine) as database_session:
        rows = database_session.scalars(select(Template)).all()
    assert len(rows) == 2
    assert sum(row.is_default for row in rows) == 1


def test_concurrent_equivalent_names_return_conflict_not_500(
    independent_template_clients: tuple[TestClient, TestClient, Engine],
) -> None:
    first, second, engine = independent_template_clients
    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = [
            future.result(timeout=10)
            for future in (
                executor.submit(_create, first, name="Race Pitch"),
                executor.submit(_create, second, name="  race pitch  "),
            )
        ]

    assert sorted(response.status_code for response in responses) == [201, 409]
    assert all(response.status_code != 500 for response in responses)
    conflict = next(response for response in responses if response.status_code == 409)
    _assert_error(conflict, status=409, code="template_name_conflict")
    with Session(engine) as database_session:
        rows = database_session.scalars(select(Template)).all()
    assert len(rows) == 1 and rows[0].is_default is True


def test_concurrent_duplicate_and_default_mutations_preserve_invariants(
    independent_template_clients: tuple[TestClient, TestClient, Engine],
) -> None:
    first, second, engine = independent_template_clients
    source = _create(first, name="Concurrent Source")
    target = _create(first, name="Concurrent Target")

    with ThreadPoolExecutor(max_workers=2) as executor:
        duplicates = [
            future.result(timeout=10)
            for future in (
                executor.submit(
                    first.post, f"{TEMPLATE_PATH}/{source.json()['id']}/duplicate"
                ),
                executor.submit(
                    second.post, f"{TEMPLATE_PATH}/{source.json()['id']}/duplicate"
                ),
            )
        ]
        defaults = [
            future.result(timeout=10)
            for future in (
                executor.submit(
                    first.post, f"{TEMPLATE_PATH}/{source.json()['id']}/default"
                ),
                executor.submit(
                    second.post, f"{TEMPLATE_PATH}/{target.json()['id']}/default"
                ),
            )
        ]

    assert all(response.status_code == 201 for response in duplicates)
    assert {response.json()["name"] for response in duplicates} == {
        "Concurrent Source Copy",
        "Concurrent Source Copy 2",
    }
    assert all(response.status_code == 200 for response in defaults)
    with Session(engine) as database_session:
        rows = database_session.scalars(select(Template)).all()
    assert sum(row.is_default for row in rows) == 1
    assert len({row.name.casefold() for row in rows}) == len(rows)


def test_concurrent_default_selection_and_delete_never_breaks_default_invariant(
    independent_template_clients: tuple[TestClient, TestClient, Engine],
) -> None:
    first, second, engine = independent_template_clients
    old_default = _create(first, name="Old Default")
    new_default = _create(first, name="New Default")

    with ThreadPoolExecutor(max_workers=2) as executor:
        selected = executor.submit(
            first.post, f"{TEMPLATE_PATH}/{new_default.json()['id']}/default"
        )
        deleted = executor.submit(
            second.delete, f"{TEMPLATE_PATH}/{old_default.json()['id']}"
        )
        responses = [selected.result(timeout=10), deleted.result(timeout=10)]

    assert responses[0].status_code == 200
    assert responses[1].status_code in {204, 409}
    assert all(response.status_code != 500 for response in responses)
    with Session(engine) as database_session:
        rows = database_session.scalars(select(Template)).all()
    assert rows
    assert sum(row.is_default for row in rows) == 1
