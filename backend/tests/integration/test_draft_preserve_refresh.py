from copy import deepcopy
from uuid import UUID

import pytest

from app.db.models.outreach_drafts import OutreachDraft
from app.workers.celery_app import celery_app
from tests.integration.test_outreach_drafts import (
    draft_setup,
    compose,
    get_compose,
    values_for,
)
from tests.integration.test_outreach_draft_runtime import execute_fixture


@pytest.mark.parametrize("mode", ["unchanged", "unsaved", "partial"])
def test_work_edit_refresh_preserves_explicit_values_without_dispatch(
    auth_client, session, monkeypatch, mode
):
    activity, selections, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=2
    )
    queued = []
    monkeypatch.setattr(
        celery_app, "send_task", lambda name, args: queued.append((name, args))
    )
    composition = compose(auth_client, activity, batch, template).json()
    calls = []
    run = execute_fixture(session, calls)
    for _, args in queued:
        run(args[0])
    original = get_compose(auth_client, composition["id"])
    draft = original["drafts"][0]
    row = session.get(OutreachDraft, UUID(draft["id"]))
    assert not row.manual_overrides
    values = deepcopy(draft["values"])
    if mode == "unsaved":
        values["observation"] = "User retained an unsaved observation."
    elif mode == "partial":
        values = {key: "" for key in values}
    queued.clear()
    selection = selections[0]
    works = auth_client.get(
        f"/api/v2/library/creators/{selection['creator_id']}/works"
    ).json()
    work = works["items"][0]
    updated = auth_client.patch(
        f"/api/v2/library/creators/{selection['creator_id']}/works/{work['id']}",
        json={
            "expected_revision": work["revision"],
            "evidence_excerpt": "New recorded observation.",
            "verification_notes": "Editor checked the referenced source.",
        },
    )
    assert updated.status_code == 200, updated.text
    fresh = get_compose(auth_client, composition["id"])["drafts"][0]
    assert fresh["source_changed"]
    body = {
        "expected_revision": draft["revision"],
        "context_token": draft["context_token"],
        "preserve_values": True,
        "values": values,
    }
    path = f"/api/v2/outreach/drafts/{draft['id']}/refresh"
    assert auth_client.post(path, json=body).status_code == 409
    assert (
        get_compose(auth_client, composition["id"])["drafts"][0]["values"]
        == draft["values"]
    )
    body["context_token"] = fresh["context_token"]
    response = auth_client.post(path, json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["values"] == values
    assert saved["status"] == ("needs_repair" if mode == "partial" else "succeeded")
    assert saved["input"]["work"]["evidence_excerpt"] == "New recorded observation."
    assert (
        saved["slot_sources"]["observation"]["evidence_excerpt"]
        == "New recorded observation."
    )
    assert (
        not saved["source_changed"]
        and not saved["sender_facts"]
        and not saved["sender_facts_valid"]
    )
    session.refresh(row)
    assert row.manual_overrides == values
    assert not queued
    # A lost response must be resolved by readback, not overwriting with old revision.
    assert auth_client.post(path, json=body).status_code == 409
    final = get_compose(auth_client, composition["id"])
    assert final["drafts"][0] == saved
    assert final["drafts"][1] == original["drafts"][1]


@pytest.mark.parametrize(
    "extra",
    [
        {"preserve_values": True},
        {"preserve_values": True, "values": {"firstName": "Only one key"}},
        {
            "preserve_values": False,
            "values": {
                "firstName": "",
                "channelName": "",
                "reference": "",
                "observation": "",
            },
        },
    ],
)
def test_preserve_refresh_requires_explicit_unambiguous_four_values(
    auth_client, session, monkeypatch, extra
):
    activity, _, batch, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    monkeypatch.setattr(celery_app, "send_task", lambda *a, **k: None)
    composition = compose(auth_client, activity, batch, template).json()
    draft = composition["drafts"][0]
    response = auth_client.post(
        f"/api/v2/outreach/drafts/{draft['id']}/refresh",
        json={
            "expected_revision": draft["revision"],
            "context_token": draft["context_token"],
            **extra,
        },
    )
    assert response.status_code == 422
    assert get_compose(auth_client, composition["id"])["drafts"][0] == draft
