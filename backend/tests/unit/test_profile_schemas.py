from math import inf, nan
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.profiles import GameProfileDetail


class SecretBearingObject:
    def __repr__(self) -> str:
        return "SecretBearingObject(api_secret='never-stringify-secret')"


def test_profile_response_schema_sanitizes_json_without_route_helpers() -> None:
    detail = GameProfileDetail(
        id=uuid4(),
        name="Schema Boundary",
        steam_app_id="schema-boundary",
        canonical_url="https://store.steampowered.com/app/schema-boundary",
        favorite=False,
        current_facts={
            "name": "Schema Boundary",
            "api_secret": "never-return-secret",
        },
        brief={"summary": "Public", "hidden_rank": 1},
        source_status={"steam": {"status": "current"}},
        last_analyzed_at=None,
        next_analysis_at=None,
        analysis={"match_result": {"score": 0.99, "reasons": ["Fit"]}},
        model_metadata={"analysis_model": "test-model"},
        prompt_metadata={"version": "game-v1", "id_token": "never-return-token"},
    )

    assert detail.current_facts == {"name": "Schema Boundary"}
    assert detail.brief == {"summary": "Public"}
    assert detail.analysis == {"match_result": {"reasons": ["Fit"]}}
    assert detail.prompt_metadata == {"version": "game-v1"}


def test_profile_response_filters_security_semantics_across_key_styles() -> None:
    detail = _game_detail(
        current_facts={
            "public": "keep",
            "authorization": "secret",
            "Auth-Header": "secret",
            "authHeaders": {"value": "secret"},
            "JWT": "secret",
            "passwd": "secret",
            "PWD": "secret",
            "bearer": "secret",
            "cookie": "secret",
            "session credential": "secret",
            "clientSecret": "secret",
            "token_payload": "secret",
            "API Key": "secret",
            "accessKey": "secret",
            "private_key": "secret",
            "Signing-Key": "secret",
            "encryptionKey": "secret",
            "auth_key": "secret",
            "apikey": "secret",
            "accesskey": "secret",
            "authheader": "secret",
            "sessionid": "secret",
            "tokenpayload": "secret",
            "nested": [{"safe": True, "Token Data": "secret"}],
        }
    )

    assert detail.current_facts == {
        "public": "keep",
        "nested": [{"safe": True}],
    }


def test_profile_response_preserves_public_metrics_and_filters_contextual_metrics(
) -> None:
    detail = _game_detail(
        current_facts={
            "score": 88,
            "rank": "Gold tier",
            "review_score": 91,
            "match_result": {
                "score": 0.98,
                "rank": 1,
                "display_order": 2,
                "reasons": ["Public reason"],
                "scorecard_label": "Public scorecard",
                "ordered_features": ["Public feature"],
            },
            "hidden_rank": 3,
            "backendOrder": 4,
            "privateScore": 0.5,
            "internal metrics": {
                "score": 0.7,
                "summary": "Public summary",
            },
            "private analysis": {
                "rank": 5,
                "summary": "Public private-context summary",
            },
        }
    )

    assert detail.current_facts == {
        "score": 88,
        "rank": "Gold tier",
        "review_score": 91,
        "match_result": {
            "reasons": ["Public reason"],
            "scorecard_label": "Public scorecard",
            "ordered_features": ["Public feature"],
        },
        "internal metrics": {"summary": "Public summary"},
        "private analysis": {"summary": "Public private-context summary"},
    }


@pytest.mark.parametrize(
    "unsupported",
    [
        ({"api_secret": "tuple-secret"},),
        {"set-secret"},
        SecretBearingObject(),
        nan,
        inf,
        -inf,
        {1: "non-string-key"},
    ],
    ids=[
        "tuple",
        "set",
        "object",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "non-string-object-key",
    ],
)
def test_profile_response_rejects_non_json_values_without_stringifying(
    unsupported: object,
) -> None:
    with pytest.raises(ValidationError):
        _game_detail(current_facts={"nested": [unsupported]})


def _game_detail(*, current_facts: object) -> GameProfileDetail:
    return GameProfileDetail(
        id=uuid4(),
        name="Schema Policy",
        steam_app_id="schema-policy",
        canonical_url="https://store.steampowered.com/app/schema-policy",
        favorite=False,
        current_facts=current_facts,
        brief={"summary": "Public"},
        source_status={"steam": {"status": "current"}},
        last_analyzed_at=None,
        next_analysis_at=None,
        analysis={"summary": "Public"},
        model_metadata={"analysis_model": "test-model"},
        prompt_metadata={"version": "game-v1"},
    )
