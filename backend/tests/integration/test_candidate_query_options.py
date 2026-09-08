from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.db.models.discovery import Activity, DiscoveryCandidate
from app.db.models.profiles import GameProfile
from app.repositories.library_v2 import game_detail
from tests.integration.test_discovery_runtime import make_query
from tests.integration.test_library_query_options import creator, work, NOW


def setup_query(session):
    query = make_query(session)
    activity = session.get(Activity, query.activity_id)
    game = session.get(GameProfile, activity.game_id)
    game.reference_works = [{"id": str(uuid4()), "name": "Reference"}]
    session.flush()
    game_snapshot = game_detail(game).model_dump(mode="json")
    query.source_snapshot = {
        "game": game_snapshot,
        "references": game_snapshot["reference_works"],
    }
    activity.source_snapshot = query.source_snapshot
    rows = []
    for index, (title, followers) in enumerate(
        [
            ("A Current", 10),
            ("B Reference", 100),
            ("C Other", None),
            ("D Title only", 0),
        ]
    ):
        person = creator(session, f"UCperson{index}", title, followers=followers)
        fields = (
            {
                "evidence_excerpt": "Observed a specific scene",
                "verification_notes": "Source checked",
            }
            if index < 3
            else {}
        )
        if index == 0 or index == 3:
            fields["game_id"] = str(game.id)
        if index == 1:
            fields["work_name"] = "Reference"
        work(session, person, title, days=index, **fields)
        row = DiscoveryCandidate(
            query_id=query.id,
            creator_id=person.id,
            platform="youtube",
            account_id=person.platform_account_id,
            identity_revision=person.identity_revision,
            account_snapshot={"account_id": person.platform_account_id},
            ordinal=index + 1,
            added_at=NOW + timedelta(days=index),
        )
        session.add(row)
        session.flush()
        rows.append(row)
    query.result_count = len(rows)
    session.flush()
    return query, rows


@pytest.mark.parametrize(
    "evidence,index",
    [("current_game", 0), ("reference_game", 1), ("related_content", 2), ("none", 3)],
)
def test_evidence_filters_whole_query_before_page_without_title_playing_inference(
    auth_client, session, evidence, index
):
    query, rows = setup_query(session)
    before = query.conditions.copy(), query.result_count, query.provider_states.copy()
    response = auth_client.get(
        f"/api/v2/discovery/queries/{query.id}/results",
        params={"evidence": evidence, "limit": 1},
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    item = response.json()["items"][0]
    assert item["id"] == str(rows[index].id)
    assert item["evidence_groups"] == ([] if evidence == "none" else [evidence])
    assert item["selected"] is False
    assert (query.conditions, query.result_count, query.provider_states) == before
    assert all(not row.selected for row in rows)


def test_candidate_order_global_and_unknown_values_after_known(auth_client, session):
    query, rows = setup_query(session)
    path = f"/api/v2/discovery/queries/{query.id}/results"
    followers = auth_client.get(path, params={"sort": "followers", "limit": 1}).json()
    assert followers["items"][0]["id"] == str(rows[1].id)
    unknown = auth_client.get(
        path, params={"sort": "followers", "limit": 1, "offset": 3}
    ).json()
    assert unknown["items"][0]["id"] == str(rows[2].id)
    for sort in ("recent_publish", "recent_added"):
        assert auth_client.get(path, params={"sort": sort, "limit": 1}).json()["items"][
            0
        ]["id"] == str(rows[3].id)


def test_existing_relevance_score_hidden_and_stale_evaluation_not_used(
    auth_client, session
):
    from app.db.models.discovery_evaluation import EvaluationRun, EvaluationItem
    from app.discovery.evaluation_snapshot import creator_snapshot, digest, game_data
    from app.db.models.profiles import CreatorProfile

    query, rows = setup_query(session)
    run = EvaluationRun(
        query_id=query.id,
        source_snapshot=query.source_snapshot,
        game_fingerprint=digest(game_data(query.source_snapshot)),
        method_version="fixture",
        status="completed",
    )
    session.add(run)
    session.flush()
    for row, score in [(rows[0], 10), (rows[1], 90)]:
        person = session.get(CreatorProfile, row.creator_id)
        snapshot, fingerprint = creator_snapshot(person, row.id)
        session.add(
            EvaluationItem(
                run_id=run.id,
                candidate_id=row.id,
                creator_id=row.creator_id,
                input_order=row.ordinal,
                snapshot=snapshot,
                fingerprint=fingerprint,
                score=score,
                screening_selected=True,
                match_brief={"cited_work_ids": []},
            )
        )
    session.flush()
    path = f"/api/v2/discovery/queries/{query.id}/results"
    response = auth_client.get(path, params={"sort": "relevance", "limit": 1}).json()
    assert response["items"][0]["id"] == str(rows[1].id)
    assert response["items"][0]["relevance_status"] == "available"
    assert "score" not in response["items"][0]
    person = session.get(CreatorProfile, rows[1].creator_id)
    person.manual_overrides = {**person.manual_overrides, "name": "Edited reference"}
    session.flush()
    refreshed = auth_client.get(path, params={"sort": "relevance"}).json()
    assert refreshed["items"][0]["id"] == str(rows[0].id)
    stale = next(v for v in refreshed["items"] if v["id"] == str(rows[1].id))
    assert stale["relevance_status"] == "stale"
    assert session.scalar(select(EvaluationRun.id)) == run.id


def test_query_option_validation_and_rebound_identity_evidence(auth_client, session):
    from app.db.models.profiles import CreatorProfile

    query, rows = setup_query(session)
    person = session.get(CreatorProfile, rows[0].creator_id)
    person.identity_revision += 1
    session.flush()
    path = f"/api/v2/discovery/queries/{query.id}/results"
    response = auth_client.get(path, params={"evidence": "current_game"})
    assert response.json()["total"] == 0
    assert auth_client.get(path, params={"evidence": "invented"}).status_code == 422
    assert auth_client.get(path, params={"sort": "invented"}).status_code == 422
