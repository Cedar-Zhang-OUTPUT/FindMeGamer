"""Canonical fixed material must survive four-slot substitution unchanged."""

from copy import deepcopy

import pytest


SUBJECT = "Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG"
FIXED_HASH = "0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93"
RAW_HASH = "6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd"
VALUES = {
    "firstName": "Jo",
    "channelName": "Jo & Co",
    "reference": "The abandoned station",
    "observation": "contrasted the quiet station with the sudden reveal.",
}


def test_canonical_source_is_exact_and_render_changes_only_four_ranges():
    from app.outreach.locked_templates import canonical_template, render_locked

    spec = canonical_template()
    assert spec["subject"] == SUBJECT
    assert spec["fixed_hash"] == FIXED_HASH
    assert spec["raw_hash"] == RAW_HASH
    assert spec["source_revision"] == 69
    assert spec["source_steam_app_id"] == "4952700"
    assert len(spec["fixed_fragments"]) == 5
    before = deepcopy(spec)
    result = render_locked(SUBJECT, spec["fixed_fragments"], VALUES, FIXED_HASH)
    assert spec == before
    assert result["subject"] == SUBJECT and result["fixed_hash"] == FIXED_HASH
    assert result["html"].count("<p>") == 20
    assert "<b>LIMINAL: Within </b>" in result["html"]
    assert "<b>Dispatch</b>" in result["html"]
    assert (
        "<p>Best,</p><p>Toki</p><p>Game Producer, Ontology Play</p><p>Hong Kong</p>"
        in result["html"]
    )
    assert "https://store.steampowered.com/app/4952700/_/" in result["html"]
    assert "Jo &amp; Co" in result["html"]
    assert "Jo & Co" in result["text"]
    assert "I’ve been following" in result["text"]
    assert "[First Name]" not in result["html"]
    assert "Yes, I'm in" not in result["html"] and "choice=" not in result["html"]


@pytest.mark.parametrize("change", ["subject", "signature", "cta"])
def test_fixed_content_changes_cannot_keep_canonical_hash(change):
    from app.outreach.locked_templates import canonical_template, render_locked

    spec = canonical_template()
    subject, fragments = spec["subject"], list(spec["fixed_fragments"])
    if change == "subject":
        subject += " Changed"
    elif change == "signature":
        fragments[-1] = fragments[-1].replace("Toki", "Another sender")
    else:
        fragments[-1] += "<p>Yes, I'm in</p>"
    with pytest.raises(ValueError):
        render_locked(subject, fragments, VALUES, FIXED_HASH)


@pytest.mark.parametrize(
    "values",
    [
        VALUES | {"subject": "Invented subject"},
        {k: v for k, v in VALUES.items() if k != "channelName"},
        VALUES | {"firstName": ""},
        VALUES | {"reference": "[Unfilled reference]"},
        VALUES | {"channelName": "Hello\nWorld"},
        VALUES | {"observation": "missing terminal full stop"},
        VALUES | {"observation": "<script>unsafe</script>."},
    ],
)
def test_exact_four_plain_filled_slots_and_final_period_are_required(values):
    from app.outreach.locked_templates import canonical_template, render_locked

    spec = canonical_template()
    with pytest.raises(ValueError):
        render_locked(SUBJECT, spec["fixed_fragments"], values, FIXED_HASH)


@pytest.mark.parametrize(
    "fragments",
    [
        ["<p>Hi ", ", from ", " about ", ". ", "</p><script>alert(1)</script>"],
        ['<p onclick="run()">Hi ', ", from ", " about ", ". ", "</p>"],
        [
            "<p>Hi ",
            ", from ",
            " about ",
            ". ",
            '<a href="javascript:run()">Open</a></p>',
        ],
        ['<p><a href="https://example.test/', '">', "</a>", "", "</p>"],
    ],
)
def test_new_explicit_fixed_version_rejects_active_markup_and_attribute_slots(
    fragments,
):
    from app.outreach.locked_templates import validate_fixed_template

    with pytest.raises(ValueError):
        validate_fixed_template("New game", fragments)


def test_explicit_new_fixed_version_is_independent_of_canonical():
    from app.outreach.locked_templates import (
        canonical_template,
        validate_fixed_template,
        render_locked,
    )

    fragments = ["<p>Hi ", ", channel ", ", your work ", ": ", "</p><p>New Game</p>"]
    fixed_hash = validate_fixed_template("New game", fragments)
    result = render_locked("New game", fragments, VALUES, fixed_hash)
    assert result["subject"] == "New game"
    assert result["text"].endswith("New Game")
    assert canonical_template()["fixed_hash"] == FIXED_HASH


def test_real_work_title_brackets_are_not_mistaken_for_unfilled_placeholders():
    from app.outreach.locked_templates import canonical_template, render_locked

    spec = canonical_template()
    title = "LIMINAL: Within [Full Playthrough]"
    rendered = render_locked(
        SUBJECT, spec["fixed_fragments"], VALUES | {"reference": title}, FIXED_HASH
    )
    assert title in rendered["text"]


@pytest.mark.parametrize(
    "value",
    [
        "[First Name]",
        "[Channel Name]",
        "[Reference Game / Video]",
        "[specific observation about their commentary, humor, pacing, or approach to story games].",
    ],
)
def test_canonical_unfilled_placeholders_remain_rejected(value):
    from app.schemas.outreach_drafts import SlotValues

    with pytest.raises(ValueError):
        SlotValues.model_validate(VALUES | {"reference": value})
