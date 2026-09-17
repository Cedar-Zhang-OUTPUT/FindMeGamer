import pytest
from fmg_agent.email.templates import get_template, list_templates, render_template
from fmg_agent.errors import ApiError
from test_email_sending import sending, headers


def values():
    return dict(creator_name="Alex", channel_name="Example Channel", reference_work="Dispatch",
                specific_observation="explained the branching narrative", game_download_url="https://store.steampowered.com/app/4952700/")


def test_catalog_and_source_template_content():
    catalog = {t["id"]: t for t in list_templates()}
    assert catalog["liminal-outreach"]["name"] == "Liminal Outreach"
    assert catalog["game-outreach"]["version"] == "2"
    template = get_template("liminal-outreach", "1")
    assert template["source"]["revision_id"] == 88
    rendered = render_template(template, values())
    assert rendered["subject"] == "Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG"
    for content in ("I’m Toki", "Hong Kong", "PARANORMASIGHT: The Seven Mysteries of Honjo", "branching choices and QTEs", "no obligation to cover it"):
        assert content in rendered["text"] and content in rendered["html"]
    v = values(); v["specific_observation"] = "<script>unsafe</script>"
    assert "<script>" not in render_template(template, v)["html"]
    del v["reference_work"]
    with pytest.raises(ApiError):
        render_template(template, v)


def test_liminal_outreach_has_independent_live_buttons_without_sending(sending):
    app, client, owner, _, _ = sending
    app.state.settings.outreach_public_url = "https://service.example.com"
    result = client.post("/v1/outreach/tasks", headers=headers(owner, "liminal-template"), json={
        "name": "Liminal preview", "template_id": "liminal-outreach", "template_version": "1",
        "recipients": [{"creator_id": name, "to": name+"@example.com", "variables": values()} for name in ("alice", "bob")],
    })
    assert result.status_code == 201
    task = result.json()["data"]
    assert task["state"] == "awaiting_approval"
    messages = [r["message"] for r in task["recipients"]]
    assert messages[0]["html"] != messages[1]["html"]
    for message in messages:
        assert message["html"].index("choice=yes") < message["html"].index("</body>")
        assert "choice=no" in message["html"]
        assert "<!--FMG_RESPONSE_ACTIONS-->" not in message["html"]
