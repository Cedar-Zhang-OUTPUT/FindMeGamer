from copy import deepcopy

import pytest

from app.db.models.profiles import GameProfile
from app.integrations.errors import TransientIntegrationError
from app.repositories.library_v2 import LibraryGamesRepository, game_detail
from app.schemas.library_v2 import GameCreate, GamePatch
from tests.integration.test_game_analysis_commit import (
    Steam,
    _job,
    _pipeline,
    _profile,
    committed_factory,
)


@pytest.mark.parametrize("failure", [False, True])
def test_reanalysis_never_overwrites_manual_game_or_references(
    committed_factory, failure
):
    profile_id = _profile(committed_factory)
    with committed_factory.begin() as session:
        updated = LibraryGamesRepository(session).patch(
            profile_id,
            GamePatch(
                expected_revision=0,
                name="Human title",
                website_url="https://studio.example/game",
                tags=["Human tag"],
                description=None,
                reference_works=[
                    {"name": "Reference work", "reason": "Shared audience"}
                ],
            ),
        )
        manual = deepcopy(updated.manual_overrides)
        references = deepcopy(updated.reference_works)
        source = deepcopy(updated.current_facts)
        identity = updated.canonical_url
    job_id = _job(committed_factory)
    pipeline = _pipeline(
        committed_factory,
        steam=Steam(
            failure=TransientIntegrationError("test_failure") if failure else None
        ),
    )
    if failure:
        with pytest.raises(TransientIntegrationError):
            pipeline.run(job_id)
    else:
        assert pipeline.run(job_id) == profile_id
    with committed_factory() as session:
        profile = session.get(GameProfile, profile_id)
        assert profile.manual_overrides == manual
        assert profile.reference_works == references
        assert profile.manual_revision == 1 and profile.sort_name == "Human title"
        assert profile.canonical_url == identity
        if failure:
            assert profile.current_facts == source
        else:
            assert profile.current_facts != source
        assert game_detail(profile).description is None


def test_first_analysis_reuses_manual_steam_seed_uuid(committed_factory):
    with committed_factory.begin() as session:
        profile = LibraryGamesRepository(session).create(
            GameCreate(name="Publisher title", steam_app_id="1245620")
        )
        profile_id = profile.id
    job_id = _job(committed_factory)
    assert _pipeline(committed_factory).run(job_id) == profile_id
    with committed_factory() as session:
        profile = session.get(GameProfile, profile_id)
        assert profile.last_analyzed_at is not None
        assert profile.sort_name == "Publisher title"
        assert game_detail(profile).source_fields.name != "Publisher title"


def test_business_identity_edits_do_not_invalidate_successful_analysis_job(
    committed_factory,
):
    job_id = _job(committed_factory)
    profile_id = _pipeline(committed_factory).run(job_id)
    with committed_factory.begin() as session:
        LibraryGamesRepository(session).patch(
            profile_id,
            GamePatch(
                expected_revision=0,
                steam_app_id="2345678",
                website_url="https://studio.example/new",
            ),
        )
    # Replaying a successful worker validates identity rather than analyzing again.
    assert _pipeline(committed_factory).run(job_id) == profile_id
