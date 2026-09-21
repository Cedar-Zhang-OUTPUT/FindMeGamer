import pytest
from test_email_jobs import gateway, headers


def test_template_catalog_requires_auth_and_exposes_variables(gateway):
    _, client, _, _, read = gateway
    assert client.get("/v1/email/templates").status_code == 401
    listing = client.get("/v1/email/templates", headers=headers(read))
    assert listing.status_code == 200
    assert listing.json()["data"][0]["id"] == "game-outreach"
    detail = client.get("/v1/email/templates/game-outreach", headers=headers(read))
    assert detail.status_code == 200
    assert detail.json()["data"]["variables"]["game_url"]["type"] == "url"


def variables():
    from test_unified_template import unified_values
    result = unified_values("New Game")
    result["game_summary"] = "A puzzle adventure."
    result["creator_name"] = "Creator"
    return result


def test_template_renders_selected_game_as_literal_text():
    from fmg_agent.email.templates import get_template, render_template

    values = variables()
    values["creator_name"] = "<b>A</b>"
    result = render_template(get_template("game-outreach", "4"), values)
    assert "New Game" in result["subject"]
    assert "A puzzle adventure." in result["text"]
    assert "LIMINAL" not in result["text"]
    assert "<b>A</b>" in result["text"]
    assert "<b>A</b>" not in result["html"]
    assert result["format"] == "signature_image"


@pytest.mark.parametrize("change", ["missing", "extra", "wrong_type", "unsafe_url"])
def test_bad_variables_rejected_without_values_in_error(change):
    from fmg_agent.email.templates import get_template, render_template
    from fmg_agent.errors import ApiError

    values = variables()
    if change == "missing":
        del values["game_name"]
    elif change == "extra":
        values["unexpected"] = "private-value"
    elif change == "wrong_type":
        values["game_name"] = ["private-value"]
    else:
        values["game_url"] = "javascript:private-value"
    with pytest.raises(ApiError) as error:
        render_template(get_template("game-outreach", "4"), values)
    assert error.value.status == 422
    assert "private-value" not in error.value.message


def test_unknown_template_and_version_are_explicit():
    from fmg_agent.email.templates import get_template
    from fmg_agent.errors import ApiError

    with pytest.raises(ApiError) as error:
        get_template("missing", "1")
    assert error.value.status == 404
    with pytest.raises(ApiError) as error:
        get_template("game-outreach", "missing")
    assert error.value.status == 409
