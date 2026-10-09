"""Formal subjects apply to new previews, never by mutating approved snapshots."""

import pytest

from fmg_agent.email.templates import get_template, render_template
from fmg_agent.errors import ApiError
from test_email_sending import headers, sending
from test_unified_template import unified_values
from test_liminal_fixed_copy import personalization, FIXED_BLOCK


@pytest.mark.parametrize(
    "template_id,values,subject",
    [
        (
            "game-outreach",
            unified_values(),
            "Thought you might enjoy It Takes Two — a cooperative adventure",
        ),
        (
            "liminal-outreach",
            personalization(),
            "Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG",
        ),
    ],
)
def test_new_rendered_subjects_have_no_internal_test_prefix(
    template_id, values, subject
):
    result = render_template(get_template(template_id), values)
    assert result["subject"] == subject
    if template_id == "liminal-outreach":
        assert result["text"].endswith(FIXED_BLOCK)


@pytest.mark.parametrize(
    "template_id,version", [("game-outreach", "4"), ("liminal-outreach", "5")]
)
def test_internal_test_versions_cannot_generate_new_drafts(template_id, version):
    with pytest.raises(ApiError) as error:
        get_template(template_id, version)
    assert error.value.code == "template_version_changed"


def test_saved_internal_test_preview_is_not_rewritten_or_approved_for_new_copy(
    sending, monkeypatch
):
    import fmg_agent.email.sending as store
    from fmg_agent.outreach import pending

    app, client, owner, _, _ = sending
    old = dict(get_template("game-outreach"))
    old.update(
        version="4",
        subject="Internal Test — Thought you might enjoy ${game_name} — ${game_tagline}",
    )
    # Simulate an immutable preview created by the old catalog, with real persistence.
    with monkeypatch.context() as patch:
        patch.setattr(store, "get_template", lambda *args: old)
        response = client.post(
            "/v1/email/previews",
            headers=headers(owner),
            json={
                "template_id": "game-outreach",
                "template_version": "4",
                "to": "alex@example.com",
                "variables": unified_values(),
            },
        )
    assert response.status_code == 201
    saved = response.json()["data"]
    assert saved["message"]["subject"].startswith("Internal Test — ")
    reread = client.get("/v1/email/previews/" + saved["id"], headers=headers(owner))
    assert reread.json()["data"] == saved
    fresh = client.post(
        "/v1/email/previews",
        headers=headers(owner),
        json={
            "template_id": "game-outreach",
            "template_version": "5",
            "to": "alex@example.com",
            "variables": unified_values(),
        },
    )
    assert fresh.status_code == 201
    assert fresh.json()["data"]["id"] != saved["id"]
    assert fresh.json()["data"]["message"]["subject"].startswith(
        "Thought you might enjoy "
    )
    assert pending(app.state.sessions) == []
