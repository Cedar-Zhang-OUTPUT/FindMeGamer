"""Versioned, server-owned templates. No user-supplied executable templates."""

from html import escape
from importlib.resources import files
import json
from string import Template

from ..errors import ApiError
from .urls import public_url

TEMPLATE_FILES = {
    "game-outreach": "game-outreach.json",
    "liminal-outreach": "liminal-outreach.json",
}


def get_template(template_id, version=None):
    filename = TEMPLATE_FILES.get(template_id)
    if filename is None:
        raise ApiError(404, "template_not_found", "Template was not found.")
    definition = json.loads(
        files("fmg_agent.email").joinpath("template_data", filename).read_text()
    )
    # Keep version 1 available for callers with an existing template contract.
    if template_id == "game-outreach" and version != "1":
        definition["version"] = "2"
        definition["html"] = files("fmg_agent.email").joinpath(
            "template_data", "game-outreach-v2.html"
        ).read_text()
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
        part: Template(definition[part]).substitute(
            {key: escape(value, quote=True) for key, value in values.items()}
            if part == "html"
            else values
        )
        for part in ("subject", "text", "html")
    }
    if "\r" in result["subject"] or "\n" in result["subject"]:
        raise ApiError(
            422,
            "template_variables_invalid",
            "Subject variables must not contain line breaks.",
        )
    return result
