"""Mail evidence priority, not a discovery or matching eligibility filter."""


def choose_recorded_work(works):
    recorded = [
        work
        for work in works
        if all(
            work.get(key)
            for key in ("source_url", "evidence_excerpt", "verification_notes")
        )
    ]
    priority = {"current_game": 0, "reference_game": 1, "related_content": 2}
    return min(
        recorded, key=lambda work: priority.get(work.get("relation"), 2), default=None
    )
