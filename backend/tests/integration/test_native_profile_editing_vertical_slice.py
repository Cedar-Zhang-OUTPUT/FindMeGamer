"""Real routes, PostgreSQL and publication; upstream acquisition/AI are fixtures.

Would fail if publication erased overrides, reset used an old source, PATCH lost
revision protection, or Match reread mutable profiles instead of freezing inputs.
"""
from copy import deepcopy
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db.models.match import MatchCandidateInput, MatchTask
from tests.integration import test_game_analysis_commit as games
from tests.integration import test_creator_analysis_commit as creators


def test_native_profile_editing_vertical_slice(auth_client, session):
    factory = sessionmaker(
        bind=session.get_bind(), expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    game_id = games._pipeline(factory).run(games._job(factory))
    creator_id = creators._pipeline(factory, clock=lambda: datetime.now(UTC)).run(creators._job(factory))

    def match():
        response = auth_client.post(
            "/api/v1/matches", json={"game_id": str(game_id)},
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 202, response.text
        return UUID(response.json()["id"])

    def snapshot(task_id):
        session.expire_all()
        task = session.get(MatchTask, task_id)
        candidate = session.scalar(select(MatchCandidateInput).where(
            MatchCandidateInput.match_task_id == task_id,
            MatchCandidateInput.creator_id == creator_id,
        ))
        assert candidate is not None
        return deepcopy((task.locked_game_brief, task.locked_game_context,
                         candidate.locked_creator_profile))

    old_id = match()
    old_snapshot = snapshot(old_id)
    edits = []
    for kind, profile_id, field in (
        ("game", game_id, "facts.name"),
        ("creator", creator_id, "facts.title"),
    ):
        url = f"/api/v1/profiles/{kind}/{profile_id}/edit"
        before = auth_client.get(url).json()
        payload = {"expected_revision": before["revision"],
                   "changes": {field: f"Human {kind}"}, "reset_fields": []}
        saved = auth_client.patch(url, json=payload)
        assert saved.status_code == 200, saved.text
        # A second read represents reopening, not an optimistic response copy.
        assert auth_client.get(url).json() == saved.json()
        stale = auth_client.patch(url, json=payload)
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "profile_revision_conflict"
        assert auth_client.get(url).json() == saved.json()
        detail = auth_client.get(f"/api/v1/profiles/{kind}s/{profile_id}").json()
        assert detail["name"] == f"Human {kind}"
        edits.append((url, field, saved.json()))

    contact = auth_client.patch(
        f"/api/v1/profiles/creators/{creator_id}/manual",
        json={"contact_email": "native-acceptance@example.com", "notes": "Local fixture notes"},
    )
    assert contact.status_code == 200
    assert auth_client.get(edits[1][0]).json() == edits[1][2]
    new_id = match()
    new_snapshot = snapshot(new_id)
    assert new_snapshot[1]["overrides"] == {"facts.name": "Human game"}
    assert new_snapshot[2]["manual_context"]["overrides"] == {"facts.title": "Human creator"}

    # Real pipeline finalization replaces source facts transactionally.
    source = games.sample_game_source().model_copy(update={"name": "Refreshed source game"})
    assert games._pipeline(factory, steam=games.Steam(source=source)).run(games._job(factory)) == game_id
    assert creators._pipeline(factory, clock=lambda: datetime.now(UTC)).run(creators._job(factory)) == creator_id
    for url, field, saved in edits:
        refreshed = auth_client.get(url).json()
        assert refreshed["revision"] == saved["revision"] + 1
        value = next(item for item in refreshed["fields"] if item["key"] == field)
        assert value["is_overridden"]
        assert value["value"] == ("Human game" if field == "facts.name" else "Human creator")
        reset = auth_client.patch(url, json={
            "expected_revision": refreshed["revision"], "changes": {}, "reset_fields": [field],
        })
        assert reset.status_code == 200
        reset_value = next(item for item in reset.json()["fields"] if item["key"] == field)
        assert not reset_value["is_overridden"]
        assert reset_value["value"] == ("Refreshed source game" if field == "facts.name" else "Example Creator")
    detail = auth_client.get(f"/api/v1/profiles/creators/{creator_id}").json()
    assert detail["contact"]["email"] == "native-acceptance@example.com"
    assert detail["manual_notes"] == "Local fixture notes"
    assert snapshot(old_id) == old_snapshot
    assert snapshot(new_id) == new_snapshot
    comparisons = auth_client.get(f"/api/v1/matches/{new_id}").json()["profile_revisions"]
    assert {(item["profile_type"], item["snapshot_revision"], item["current_revision"])
            for item in comparisons} == {("game", 2, 4), ("creator", 2, 4)}
