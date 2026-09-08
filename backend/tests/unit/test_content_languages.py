import pytest

from app.core.content_languages import known_content_languages
from app.core.languages import language_key


@pytest.mark.parametrize(
    "label, expected",
    [
        ("en-US", "en"),
        ("pt-BR", "pt"),
        ("es-419", "es"),
        ("zh-Hant-TW", "zh-hant"),
        ("zh-TW", "zh-tw"),
        ("en-private", "en-private"),
    ],
)
def test_source_region_labels_match_presets_without_guessing_script(label, expected):
    assert language_key(label) == expected


def test_known_source_labels_preserve_original_values_and_ignore_unknown():
    values = [None, "und", "zxx", "", "en-US", "EN-us", "ja"]
    assert known_content_languages(values) == ["en-US", "ja"]
    assert values == [None, "und", "zxx", "", "en-US", "EN-us", "ja"]
