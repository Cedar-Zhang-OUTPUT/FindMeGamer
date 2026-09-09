from uuid import UUID, uuid4
from sqlalchemy import select
from app.db.models.discovery import DiscoveryCandidate
from app.db.models.discovery_evaluation import EvaluationRun, EvaluationItem
from app.db.models.profiles import CreatorProfile, CreatorWork
from tests.integration.test_discovery_evaluation import seed_query, start


def test_linked_current_game_work_is_not_lost_behind_twenty_unrelated_works(
    auth_client, session, monkeypatch
):
    query_id = seed_query(auth_client, session, monkeypatch, count=1)
    candidate = session.scalar(
        select(DiscoveryCandidate).where(DiscoveryCandidate.query_id == UUID(query_id))
    )
    creator = session.get(CreatorProfile, candidate.creator_id)
    from app.db.models.discovery import DiscoveryQuery

    game_id = session.get(DiscoveryQuery, UUID(query_id)).source_snapshot["game"]["id"]
    for index in range(21):
        session.add(
            CreatorWork(
                creator_id=creator.id,
                platform=creator.platform,
                origin="manual",
                identity_revision=creator.identity_revision,
                source_fields={},
                manual_overrides={
                    "content_title": f"Video {index}",
                    "source_url": f"https://example.com/{index}",
                    "game_id": game_id if index == 0 else None,
                    "published_at": (
                        "2020-01-01T00:00:00Z" if index == 0 else "2026-01-01T00:00:00Z"
                    ),
                },
            )
        )
    session.commit()
    session.expire(creator, ["works"])
    run_id = start(auth_client, query_id)
    item = session.scalar(
        select(EvaluationItem).where(EvaluationItem.run_id == UUID(run_id))
    )
    assert item.snapshot["creator_brief"]["match_priority"] == "current_game_work"
    assert any(work["game_id"] == game_id for work in item.snapshot["works"])


def test_results_apply_priority_before_pagination_without_dropping_type_candidates(
    auth_client, session, monkeypatch
):
    query_id = seed_query(auth_client, session, monkeypatch, count=3)
    run_id = start(auth_client, query_id)
    run = session.get(EvaluationRun, UUID(run_id))
    items = session.scalars(
        select(EvaluationItem)
        .where(EvaluationItem.run_id == run.id)
        .order_by(EvaluationItem.input_order)
    ).all()
    for index, item in enumerate(items):
        item.score = 99 - index * 10
    items[2].snapshot = items[2].snapshot | {
        "works": [
            {
                "id": str(uuid4()),
                "game_id": run.source_snapshot["game"]["id"],
                "source_url": "https://example.com/current",
            }
        ],
        "match_priority": "current_game_work",
    }
    session.commit()
    path = f"/api/v2/discovery/evaluations/{run_id}/results"
    first = auth_client.get(path, params={"limit": 1}).json()
    assert first["total"] == 3 and first["items"][0]["candidate_id"] == str(
        items[2].candidate_id
    )
    all_rows = auth_client.get(path).json()["items"]
    assert len(all_rows) == 3 and all(not row["sender_watched"] for row in all_rows)


def test_mail_chooses_recorded_current_game_from_explicit_selection(
    auth_client, session, monkeypatch
):
    from tests.integration.test_outreach_drafts import draft_setup, compose
    from tests.integration.test_activity_preparation import read, update, post
    from tests.integration.test_activity_recipient_batches import freeze

    activity, choices, _, template = draft_setup(
        auth_client, session, monkeypatch, count=1
    )
    chosen = choices[0]
    path = f"/api/v2/library/creators/{chosen['creator_id']}"
    creator = auth_client.get(path).json()
    created = post(
        auth_client,
        path + "/works",
        {
            "expected_identity_revision": creator["source_identity"]["revision"],
            "game_id": template["game_id"],
            "content_title": "Current game recorded scene",
            "source_url": "https://example.com/current-scene",
            "evidence_excerpt": "A verified garden scene",
            "verification_notes": "Operator retained source note",
        },
    )
    assert created.status_code == 201, created.text
    fresh = read(auth_client, chosen)
    updated = update(
        auth_client, fresh, work_ids=[work["id"] for work in fresh["works"]] + [created.json()["id"]]
    )
    assert updated.status_code == 200, updated.text
    batch = freeze(auth_client, activity, [updated.json()])
    composition = compose(auth_client, activity, batch, template).json()
    source = composition["drafts"][0]["input"]["work"]
    assert source["id"] == created.json()["id"]
    assert source["evidence_tier"] == "current_game"
    assert source["source_url"] == "https://example.com/current-scene"
    assert not composition["drafts"][0]["sender_facts_valid"]
