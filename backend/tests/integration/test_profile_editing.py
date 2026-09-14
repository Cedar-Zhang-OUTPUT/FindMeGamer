from copy import deepcopy

import pytest

from tests.integration.test_match_input_lock import _creator, _game


@pytest.mark.parametrize("kind,name_key", [("game", "name"), ("creator", "title")])
def test_edit_is_atomic_revisioned_and_preserves_source(
    auth_client, session, kind, name_key
):
    profile = _game() if kind == "game" else _creator(901)
    session.add(profile)
    session.flush()
    original = deepcopy(profile.current_facts)
    url = f"/api/v1/profiles/{kind}/{profile.id}/edit"
    before = auth_client.get(url)
    assert before.status_code == 200
    revision = before.json()["revision"]
    patch = {
        "expected_revision": revision,
        "changes": {f"facts.{name_key}": "Human name"},
        "reset_fields": [],
    }
    saved = auth_client.patch(url, json=patch)
    assert saved.status_code == 200
    assert saved.json()["revision"] == revision + 1
    field = next(f for f in saved.json()["fields"] if f["key"] == f"facts.{name_key}")
    assert field["value"] == "Human name" and field["is_overridden"]
    session.refresh(profile)
    assert profile.current_facts == original
    detail = auth_client.get(
        f"/api/v1/profiles/{'games' if kind == 'game' else 'creators'}/{profile.id}"
    ).json()
    assert detail["name"] == "Human name"
    assert detail["current_facts"][name_key] == "Human name"
    collection = "games" if kind == "game" else "creators"
    assert [
        item["id"]
        for item in auth_client.get(
            f"/api/v1/profiles/{collection}", params={"query": "Human name"}
        ).json()["items"]
    ] == [str(profile.id)]
    assert auth_client.patch(url, json=patch).status_code == 409
    patch["expected_revision"] += 1
    patch["changes"]["facts.canonical_url"] = "https://invalid.example"
    assert auth_client.patch(url, json=patch).status_code == 422
    assert auth_client.get(url).json() == saved.json()
    reset = auth_client.patch(
        url,
        json={
            "expected_revision": revision + 1,
            "changes": {},
            "reset_fields": [f"facts.{name_key}"],
        },
    )
    assert reset.status_code == 200
    assert (
        auth_client.get(
            f"/api/v1/profiles/{collection}", params={"query": "Human name"}
        ).json()["items"]
        == []
    )
    assert not next(
        f for f in reset.json()["fields"] if f["key"] == f"facts.{name_key}"
    )["is_overridden"]


def test_stale_creator_keeps_only_manual_projection_and_separate_contacts(
    auth_client, session
):
    creator = _creator(902)
    creator.source_status = {"youtube": "stale", "freshness": "stale"}
    session.add(creator)
    session.flush()
    url = f"/api/v1/profiles/creator/{creator.id}/edit"
    revision = auth_client.get(url).json()["revision"]
    changes = {
        "facts.title": "Human stale title",
        "analysis.content_summary": "Human retained summary",
    }
    response = auth_client.patch(
        url,
        json={"expected_revision": revision, "changes": changes, "reset_fields": []},
    )
    assert response.status_code == 200
    detail = auth_client.get(f"/api/v1/profiles/creators/{creator.id}").json()
    assert detail["current_facts"] == {"title": "Human stale title"}
    assert detail["analysis"] == {
        "content_summary": {
            "status": "available",
            "value": "Human retained summary",
            "provenance": "manual",
        }
    }
    assert detail["manual_overrides"] == changes
    assert detail["profile_revision"] == revision + 1
    assert (
        auth_client.patch(
            f"/api/v1/profiles/creators/{creator.id}/manual",
            json={"contact_email": "human@example.com", "notes": "Separate notes"},
        ).status_code
        == 200
    )
    assert auth_client.get(url).json() == response.json()


def test_manual_claims_allow_clear_and_long_text_without_false_evidence(
    auth_client, session
):
    profile = _game()
    session.add(profile)
    session.flush()
    url = f"/api/v1/profiles/game/{profile.id}/edit"
    before = auth_client.get(url)
    assert before.status_code == 200
    patch = {
        "expected_revision": before.json()["revision"],
        "changes": {
            "analysis.themes": [],
            "brief.positioning_premise": "Human description. " * 60,
            "facts.short_description": "",
        },
        "reset_fields": [],
    }
    saved = auth_client.patch(url, json=patch)
    assert saved.status_code == 200
    fields = {f["key"]: f for f in saved.json()["fields"]}
    assert fields["analysis.themes"]["value"] == []
    assert fields["facts.short_description"]["value"] == ""
    assert fields["facts.short_description"]["is_overridden"]
    detail = auth_client.get(f"/api/v1/profiles/games/{profile.id}").json()
    assert detail["analysis"]["themes"] == {
        "status": "available",
        "values": [],
        "provenance": "manual",
    }
    assert "evidence" not in detail["brief"]["positioning_premise"]
    for invalid in (
        {"facts.name": " "},
        {"analysis.themes": "not a list"},
        {"analysis.themes.0": "x"},
    ):
        patch.update(expected_revision=saved.json()["revision"], changes=invalid)
        assert auth_client.patch(url, json=patch).status_code == 422
    assert auth_client.get(url).json() == saved.json()
