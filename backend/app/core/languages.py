"""Explicit UI preset aliases for comparison only; never rewrite source labels."""

_PRESETS = (
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
)
_ALIASES = {
    alias.casefold(): code.casefold()
    for code, *aliases in _PRESETS
    for alias in (code, *aliases)
}


def language_key(value: str) -> str:
    normalized = value.strip().casefold()
    return _ALIASES.get(normalized, normalized)


def language_keys(values) -> set[str]:
    return {key for value in values if (key := language_key(value))}
