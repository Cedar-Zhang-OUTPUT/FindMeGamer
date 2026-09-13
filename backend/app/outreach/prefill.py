"""Deterministic source-backed draft suggestions, never sender confirmations."""

import re
from app.schemas.outreach_drafts import DraftSlotValues


def slot_text(value, *, limit=600):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"\s+", " ", value).strip()[:limit].strip()
    try:
        return DraftSlotValues(
            firstName=value, channelName="", reference="", observation=""
        ).firstName
    except ValueError:
        return ""


def metadata_observation(title, description, source_url):
    excerpt = slot_text(description, limit=350) or slot_text(title, limit=350)
    field = "description" if slot_text(description, limit=350) else "title"
    return {
        "text": f"used this {field} for your video: “{excerpt}”." if excerpt else "",
        "evidence_kind": "metadata",
        "source_url": source_url,
        "excerpt": excerpt,
        "source_field": field,
    }


def work_kind(work):
    if all(
        work.get(key)
        for key in ("source_url", "evidence_excerpt", "verification_notes")
    ):
        return "manual_note"
    return "metadata" if work.get("source_url") else "unavailable"


def work_observation(work):
    if work_kind(work) == "manual_note":
        excerpt = slot_text(work.get("evidence_excerpt"), limit=350)
        return (
            f"presented the scene described in the viewing notes: “{excerpt}”."
            if excerpt
            else ""
        )
    source = work.get("source_fields") or {}
    observation = source.get("outreach_observation") or {}
    if observation.get("evidence_kind") == "metadata" and observation.get(
        "source_url"
    ) == work.get("source_url"):
        return slot_text(observation.get("text"))
    return (
        metadata_observation(work.get("content_title"), "", work.get("source_url"))[
            "text"
        ]
        if work.get("source_url")
        else ""
    )


def choose_prefill_work(works, game, references):
    """Explicit game bindings first, then title hints; metadata stays metadata."""
    current = slot_text(game.get("name")).casefold()
    reference_names = [slot_text(r.get("name")).casefold() for r in references]

    def priority(work):
        title = (work.get("content_title") or work.get("work_name") or "").casefold()
        relation = work.get("relation")
        game_rank = (
            0
            if relation == "current_game" or (current and current in title)
            else (
                1
                if relation == "reference_game"
                or any(name and name in title for name in reference_names)
                else 2
            )
        )
        return (0 if work_kind(work) == "manual_note" else 1, game_rank)

    # Stable date/id ordering prevents a reload choosing a different equal-priority work.
    ordered = sorted(
        works,
        key=lambda work: (work.get("published_at") or "", work.get("id") or ""),
        reverse=True,
    )
    return min(ordered, key=priority, default={})
