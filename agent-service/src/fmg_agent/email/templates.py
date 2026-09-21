"""Versioned, server-owned templates. No user-supplied executable templates."""

from importlib.resources import files
from base64 import b64encode
from html import escape
import json
from string import Template

from ..errors import ApiError
from .urls import public_url

TEMPLATE_FILES = {
    "game-outreach": "game-outreach.json",
}


def get_template(template_id, version=None):
    filename = TEMPLATE_FILES.get(template_id)
    if filename is None:
        raise ApiError(404, "template_not_found", "Template was not found.")
    definition = json.loads(
        files("fmg_agent.email").joinpath("template_data", filename).read_text()
    )
    if version is not None and version != definition["version"]:
        raise ApiError(
            409,
            "template_version_changed",
            "Read the current template and prepare a new preview.",
        )
    return definition


def list_templates():
    return [
        {key: definition[key] for key in ("id", "version", "name")}
        for definition in (get_template(template_id) for template_id in TEMPLATE_FILES)
    ]


def render_template(definition, variables):
    schema = definition["variables"]
    if not isinstance(variables, dict) or set(variables) - set(schema):
        raise ApiError(
            422, "template_variables_invalid", "Check the declared template variables."
        )
    values = {}
    for name, field in schema.items():
        value = variables.get(name, "")
        if not isinstance(value, str) or (field["required"] and not value.strip()):
            raise ApiError(
                422, "template_variables_invalid", f"Provide text for {name}."
            )
        if field["type"] == "url":
            try:
                value = public_url(value)
            except ValueError:
                raise ApiError(
                    422,
                    "template_variables_invalid",
                    f"Provide a public HTTP(S) URL for {name}.",
                ) from None
        values[name] = value
    result = {
        part: Template(definition[part]).substitute(values)
        for part in ("subject", "text")
    }
    if "\r" in result["subject"] or "\n" in result["subject"]:
        raise ApiError(
            422,
            "template_variables_invalid",
            "Subject variables must not contain line breaks.",
        )
    result["format"] = "plain_text"
    if definition.get("format") == "signature_image":
        # Server-owned asset is snapshotted with the draft, never remotely fetched.
        result["format"] = "signature_image"
        result["html"] = (
            '<!doctype html><html><body><div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">'
            + escape(result["text"]).replace("\n", "<br>\n")
            + '</div><br><img src="cid:ontology-play-signature" alt="Ontology Play" width="335" '
            'style="width:335px;max-width:100%;height:auto"></body></html>'
        )
        result["signature_png_base64"] = b64encode(
            files("fmg_agent.email").joinpath("template_data", "ontology-play.png").read_bytes()
        ).decode("ascii")
    return result
