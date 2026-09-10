from uuid import uuid4
import pytest
from app.analysis.contracts import SteamRecommendations, SteamRecommendedItem
from app.db.models.profiles import GameProfile
from app.repositories.steam_references import (
    merge_steam_references,
    remember_reference_removals,
)
from app.repositories.library_v2 import _reference_values, game_detail
from app.schemas.library_v2 import ReferenceWork


def source(*ids, status="available"):
    return SteamRecommendations(
        status=status,
        source_url="https://store.steampowered.com/recommended/morelike/app/10/",
        items=tuple(
            SteamRecommendedItem(
                app_id=str(i),
                name=f"Game {i}",
                url=f"https://store.steampowered.com/app/{i}/",
            )
            for i in ids
        ),
    )


def profile():
    return GameProfile(
        id=uuid4(),
        steam_app_id="10",
        manual_revision=1,
        favorite=False,
        current_facts={"name": "Source"},
        source_status={},
        reference_works=[],
        manual_overrides={},
    )


def test_merge_preserves_manual_dedups_and_survives_failure_and_empty_refresh():
    p = profile()
    p.reference_works = _reference_values(
        [
            ReferenceWork(
                name="Human reference",
                url="https://store.steampowered.com/app/20/slug/?q=a",
                reason="Human reason",
            )
        ],
        [],
    )
    manual = p.reference_works[0].copy()
    merge_steam_references(p, source(20, 21))
    assert p.reference_works[0] == manual
    assert (
        len(p.reference_works) == 2
        and p.reference_works[1]["source"] == "steam_more_like_this"
    )
    before = p.reference_works.copy()
    merge_steam_references(p, source(status="unavailable"))
    assert p.reference_works == before
    assert game_detail(p).steam_recommendations.status == "unavailable"
    merge_steam_references(p, source())
    assert p.reference_works == before


def test_deleted_or_retargeted_recommendation_never_returns_but_new_one_can_append():
    p = profile()
    merge_steam_references(p, source(20, 21))
    edited = ReferenceWork.model_validate(p.reference_works[0]).model_copy(
        update={"name": "Edited title", "url": "https://example.com/my-reference"}
    )
    p.reference_works = _reference_values([edited], p.reference_works)
    merge_steam_references(p, source(20, 21, 22))
    assert [r["name"] for r in p.reference_works] == ["Edited title", "Game 22"]
    assert p.reference_works[0]["source"] == "steam_more_like_this"
    merge_steam_references(p, source(20, 21, 22))
    assert len(p.reference_works) == 2


def test_caller_cannot_forge_source_and_old_client_edit_preserves_server_provenance():
    forged = ReferenceWork(
        name="Manual", source="steam_more_like_this", source_url="https://evil.example/"
    )
    assert _reference_values([forged], [])[0]["source"] == "manual"
    p = profile()
    merge_steam_references(p, source(20))
    old_client = ReferenceWork(id=p.reference_works[0]["id"], name="Edited")
    result = _reference_values([old_client], p.reference_works)
    assert result[0]["source"] == "steam_more_like_this"
    assert result[0]["source_url"] == source().source_url


@pytest.mark.parametrize("retarget", [False, True])
def test_removed_manual_steam_reference_does_not_return_even_before_first_fetch(
    retarget,
):
    p = profile()
    p.reference_works = _reference_values(
        [
            ReferenceWork(
                name="Human reference", url="https://store.steampowered.com/app/20/"
            )
        ],
        [],
    )
    replacement = (
        _reference_values(
            [
                ReferenceWork(
                    id=p.reference_works[0]["id"],
                    name="Retargeted",
                    url="https://example.com/new",
                )
            ],
            p.reference_works,
        )
        if retarget
        else []
    )
    remember_reference_removals(p, replacement)
    p.reference_works = replacement
    merge_steam_references(p, source(20, 21))
    assert [r["name"] for r in p.reference_works] == (
        ["Retargeted", "Game 21"] if retarget else ["Game 21"]
    )
