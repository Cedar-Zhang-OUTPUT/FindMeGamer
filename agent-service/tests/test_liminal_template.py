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
    assert catalog["game-outreach"]["version"] == "3"
    template = get_template("liminal-outreach", "4")
    assert template["source"]["revision_id"] == 88
    rendered = render_template(template, values())
    assert rendered["subject"] == "Internal Test — Thought you might enjoy LIMINAL: Within — interactive film meets pixel RPG"
    for content in ("I’m Toki", "Hong Kong", "PARANORMASIGHT: The Seven Mysteries of Honjo", "branching choices and QTEs", "no obligation to cover it"):
        assert content in rendered["text"]
    v = values(); v["specific_observation"] = "<script>unsafe</script>"
    assert "<script>unsafe</script>" in render_template(template, v)["text"]
    assert rendered["format"] == "signature_image"
    assert rendered["text"].endswith("Kind regards,\n\nToki Yuan\nGame Producer, Ontology Play\nEmail: OntologyPlay@hotmail.com")
    assert "cid:ontology-play-signature" in rendered["html"]
    assert "<script>" not in render_template(template, v)["html"]
    del v["reference_work"]
    with pytest.raises(ApiError):
        render_template(template, v)


def test_liminal_outreach_plain_drafts_without_sending(sending):
    app, client, owner, _, _ = sending
    result = client.post("/v1/outreach/tasks", headers=headers(owner, "liminal-template"), json={
        "name": "Liminal preview", "template_id": "liminal-outreach", "template_version": "4",
        "recipients": [{"creator_id": name, "to": name+"@example.com", "variables": values()} for name in ("alice", "bob")],
    })
    assert result.status_code == 201
    task = result.json()["data"]
    assert task["state"] == "awaiting_approval"
    messages = [r["message"] for r in task["recipients"]]
    for message in messages:
        assert message["format"] == "signature_image"
        assert "Click here to tell us" not in message["text"]
        assert "choice=yes" not in message["text"]
