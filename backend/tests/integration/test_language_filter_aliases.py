"""Desktop language presets match saved labels without rewriting source data."""

import pytest

from app.discovery.library import evaluate_candidate, import_discovered_account
from tests.integration.test_library_query_options import creator
from tests.test_discovery_library import account, content


PRESETS = [
    ("en", "English", "英语"),
    ("ja", "Japanese", "日语"),
    ("ko", "Korean", "韩语"),
    ("zh-Hans", "Simplified Chinese", "简体中文"),
    ("zh-Hant", "Traditional Chinese", "繁体中文"),
    ("es", "Spanish", "西班牙语"),
    ("pt", "Portuguese", "葡萄牙语"),
    ("fr", "French", "法语"),
    ("de", "German", "德语"),
    ("it", "Italian", "意大利语"),
    ("ru", "Russian", "俄语"),
    ("ar", "Arabic", "阿拉伯语"),
    ("id", "Indonesian", "印尼语"),
    ("th", "Thai", "泰语"),
    ("vi", "Vietnamese", "越南语"),
]


@pytest.mark.parametrize("code,label,localized", PRESETS)
def test_preset_labels_and_codes_match_both_filters_without_storage_changes(
    auth_client, session, code, label, localized
):
    person = creator(session, "UCdiscovery", "Creator", languages=[label])
    for requested in [code, localized]:
        result = auth_client.get(
            "/api/v2/library/creators", params={"languages": requested}
        )
        assert result.status_code == 200
        assert result.json()["total"] == 1
        assert result.json()["items"][0]["languages"] == [label]
        assert evaluate_candidate(
            session, person, account(), [], {"languages": [requested]}
        )[0]
    assert person.manual_overrides["languages"] == [label]
    person.manual_overrides = {"name": "Creator", "languages": [code]}
    session.flush()
    result = auth_client.get("/api/v2/library/creators", params={"language": label})
    assert result.json()["total"] == 1
    assert evaluate_candidate(session, person, account(), [], {"languages": [label]})[0]
    assert person.manual_overrides["languages"] == [code]


def test_provider_language_alias_comparison_preserves_raw_work_metadata(session):
    value, item = account(), content(language="en")
    person = import_discovered_account(session, value, [item])
    assert evaluate_candidate(
        session, person, value, [item], {"languages": ["English"]}
    )[0]
    assert item.language == "en"
    assert person.works[0].source_fields["language"] == "en"
    person.manual_overrides = {"languages": ["French"]}
    session.flush()
    assert not evaluate_candidate(
        session, person, value, [item], {"languages": ["English"]}
    )[0]
    assert evaluate_candidate(session, person, value, [item], {"languages": ["fr"]})[0]
    assert person.manual_overrides["languages"] == ["French"]


@pytest.mark.parametrize(
    "stored,requested,expected",
    [
        ("zh-Hans", "Traditional Chinese", False),
        ("zh-Hant", "Simplified Chinese", False),
        ("zh", "Simplified Chinese", False),
        ("zh", "Traditional Chinese", False),
        ("zh", "ZH", True),
        ("Custom Dialect", " custom DIALECT ", True),
        ("Custom Dialect", "English", False),
        (" English ", " EN ", True),
    ],
)
def test_scripts_and_custom_labels_are_not_guessed(
    auth_client, session, stored, requested, expected
):
    person = creator(session, "UCdiscovery", "Creator", languages=[stored])
    result = auth_client.get(
        "/api/v2/library/creators", params={"languages": requested}
    )
    assert result.status_code == 200
    assert result.json()["total"] == int(expected)
    assert (
        evaluate_candidate(session, person, account(), [], {"languages": [requested]})[
            0
        ]
        is expected
    )
    assert person.manual_overrides["languages"] == [stored]
