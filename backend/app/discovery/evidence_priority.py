"""Matching preference from linked work identity; never a viewing attestation."""


def match_priority(snapshot, source):
    frozen = snapshot.get("match_priority")
    if frozen in ("current_game_work", "reference_game_work", "type_related_candidate"):
        return (
            "current_game_work",
            "reference_game_work",
            "type_related_candidate",
        ).index(frozen)
    current = source.get("game", {}).get("id")
    references = {
        str(item.get("name", "")).casefold()
        for item in source.get("references", [])
        if item.get("name")
    }
    priority = 2
    for work in snapshot.get("works", []):
        if not work.get("source_url"):
            continue
        if current and str(work.get("game_id")) == str(current):
            return 0
        if work.get("work_name") and work["work_name"].casefold() in references:
            priority = 1
    return priority


def ordered_items(items, source):
    # Preserve every candidate, including unranked and metadata-only records.
    return sorted(
        items,
        key=lambda item: (
            item.score is None,
            match_priority(item.snapshot, source),
            -(item.score or 0),
            item.input_order,
        ),
    )
