"""Provider content labels, not audience inference or language detection."""


def known_content_languages(values):
    result, seen = [], set()
    for value in values:
        if not isinstance(value, str):
            continue
        label = value.strip()
        key = label.casefold()
        if not label or len(label) > 255 or key in {"und", "zxx"} or key in seen:
            continue
        seen.add(key)
        result.append(label)
    return result


def creator_source_languages(creator):
    facts = creator.current_facts or {}
    if "languages" in facts:
        values = facts["languages"]
        return known_content_languages(values if isinstance(values, list) else [])
    return known_content_languages(
        work.source_fields.get("language")
        for work in creator.works
        if work.identity_revision == creator.identity_revision
        and work.platform == creator.platform
        and work.origin == "source"
    )
