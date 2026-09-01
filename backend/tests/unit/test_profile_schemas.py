import json
from math import inf, nan
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.profiles import GameProfileDetail
from tests.profile_policy_cases import (
    CONTEXT_METRIC_KEYS,
    RESTRICTED_ANCESTOR_FORMS,
    RESTRICTED_COMPACT_METRIC_FORMS,
    SECURITY_KEY_FORMS,
)


class SecretBearingObject:
    def __repr__(self) -> str:
        return "SecretBearingObject(api_secret='never-stringify-secret')"


ERROR_REPR_CANARY = "SECRET-REPR-CANARY"


class ErrorCanaryObject:
    def __repr__(self) -> str:
        return f"ErrorCanaryObject(api_secret='{ERROR_REPR_CANARY}')"


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


def test_profile_response_filters_generated_security_key_matrix() -> None:
    sensitive = {
        key: f"secret-for-{index}"
        for index, key in enumerate(sorted(SECURITY_KEY_FORMS))
    }
    detail = _game_detail(
        current_facts={
            "public": "keep",
            "key": "public lookup key",
            **sensitive,
            "outer": [
                {
                    "public_nested": True,
                    "key": "nested public lookup key",
                    **sensitive,
                }
            ],
        }
    )

    assert detail.current_facts == {
        "public": "keep",
        "key": "public lookup key",
        "outer": [
            {
                "public_nested": True,
                "key": "nested public lookup key",
            }
        ],
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


def test_profile_response_filters_generated_contextual_metric_matrix() -> None:
    restricted_contexts = {
        ancestor: {
            **{metric: 1 for metric in CONTEXT_METRIC_KEYS},
            "scorecard_label": "Public scorecard",
            "ordered_features": ["Public feature"],
            "summary": "Public summary",
        }
        for ancestor in RESTRICTED_ANCESTOR_FORMS
    }
    compact_metrics = {
        key: 1 for key in RESTRICTED_COMPACT_METRIC_FORMS
    }
    detail = _game_detail(
        current_facts={
            "score": 87,
            "rank": "Gold tier",
            "review_score": 91,
            "scorecard_label": "Public scorecard",
            "ordered_features": ["Public feature"],
            **restricted_contexts,
            **compact_metrics,
        }
    )

    assert detail.current_facts == {
        "score": 87,
        "rank": "Gold tier",
        "review_score": 91,
        "scorecard_label": "Public scorecard",
        "ordered_features": ["Public feature"],
        **{
            ancestor: {
                "scorecard_label": "Public scorecard",
                "ordered_features": ["Public feature"],
                "summary": "Public summary",
            }
            for ancestor in RESTRICTED_ANCESTOR_FORMS
        },
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


def test_profile_validation_error_never_includes_unsupported_value_repr() -> None:
    with pytest.raises(ValidationError) as captured:
        _game_detail(current_facts={"nested": [ErrorCanaryObject()]})

    assert ERROR_REPR_CANARY not in str(captured.value)
    assert ERROR_REPR_CANARY not in captured.value.json()
    assert ERROR_REPR_CANARY not in json.dumps(
        captured.value.errors(), default=repr
    )


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
