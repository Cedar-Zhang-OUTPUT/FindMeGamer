"""Validation and safe rendering for author-controlled Outreach templates."""

from __future__ import annotations

from html import escape
import re

import bleach
from markdown_it import MarkdownIt

from app.schemas.outreach import (
    ACCEPTED_RESPONSE_URL_PLACEHOLDER,
    DEFAULT_ACCEPTED_LABEL,
    DEFAULT_DECLINED_LABEL,
    DECLINED_RESPONSE_URL_PLACEHOLDER,
    RESPONSE_URL_PLACEHOLDERS,
    RenderedDelivery,
    ResponseURLs,
    TemplateContext,
    TemplateData,
)


ALLOWED_TEMPLATE_VARIABLES = frozenset(
    {
        "creator_name",
        "channel_name",
        "game_name",
        "steam_url",
        "game_summary",
        "match_reason",
        "sender_name",
    }
)

_VARIABLE_PATTERN = re.compile(r"\{\{([^{}]*)\}\}")
_SINGLE_BRACED_IDENTIFIER_PATTERN = re.compile(
    r"(?<!\{)\{\s*[A-Za-z_][A-Za-z0-9_]*\s*\}(?!\})"
)
_VALID_VARIABLE_NAME_PATTERN = re.compile(r"[a-z_][a-z0-9_]*")
_MARKDOWN_META_PATTERN = re.compile(r"([\\`*_{}\[\]<>#!|()+\->~])")
_ORDERED_LIST_PATTERN = re.compile(r"^(\s*\d+)([.)])(?=\s)", re.MULTILINE)
_LEADING_WHITESPACE_PATTERN = re.compile(r"^[ \t]+", re.MULTILINE)

_MARKDOWN = MarkdownIt(
    "commonmark",
    {
        "html": False,
        "linkify": False,
        "typographer": False,
    },
)
_ALLOWED_HTML_TAGS = frozenset(
    {"p", "br", "strong", "em", "ul", "ol", "li", "a", "blockquote", "code"}
)
_ALLOWED_HTML_ATTRIBUTES = {"a": ["href", "title"]}
_ALLOWED_HTML_PROTOCOLS = frozenset({"http", "https", "mailto"})


class TemplateValidationError(ValueError):
    """An Outreach template cannot be safely rendered as a whole."""


def validate_template_variables(text: str) -> set[str]:
    """Return referenced allowlisted variables or reject malformed syntax."""

    if type(text) is not str:
        raise TemplateValidationError("Template text must be a string.")
    if "{{{" in text or "}}}" in text:
        raise TemplateValidationError(
            "Template contains malformed variable syntax; use {{variable_name}}."
        )

    variables: set[str] = set()
    remainder_parts: list[str] = []
    previous_end = 0
    for match in _VARIABLE_PATTERN.finditer(text):
        remainder_parts.append(text[previous_end : match.start()])
        name = match.group(1)
        if _VALID_VARIABLE_NAME_PATTERN.fullmatch(name) is None:
            raise TemplateValidationError(
                "Template contains malformed variable syntax; use {{variable_name}}."
            )
        if name not in ALLOWED_TEMPLATE_VARIABLES:
            raise TemplateValidationError(f"Unknown Template variable: {name}.")
        variables.add(name)
        previous_end = match.end()
    remainder_parts.append(text[previous_end:])
    remainder = "".join(remainder_parts)

    if (
        "{{" in remainder
        or "}}" in remainder
        or _SINGLE_BRACED_IDENTIFIER_PATTERN.search(remainder) is not None
    ):
        raise TemplateValidationError(
            "Template contains malformed variable syntax; use {{variable_name}}."
        )
    return variables


def _render_variables(text: str, values: dict[str, str]) -> str:
    return _VARIABLE_PATTERN.sub(lambda match: values[match.group(1)], text)


def _escape_markdown_data(value: str) -> str:
    escaped = _MARKDOWN_META_PATTERN.sub(r"\\\1", value)
    escaped = _ORDERED_LIST_PATTERN.sub(r"\1\\\2", escaped)
    return _LEADING_WHITESPACE_PATTERN.sub(
        lambda match: "".join(
            "&#32;" if character == " " else "&#9;" for character in match.group(0)
        ),
        escaped,
    )


def _contains_header_control(value: str) -> bool:
    return any(
        ord(character) < 32 or 127 <= ord(character) <= 159 for character in value
    )


def _reject_reserved_markers(value: str) -> None:
    if any(marker in value for marker in RESPONSE_URL_PLACEHOLDERS):
        raise TemplateValidationError(
            "Template content cannot contain reserved response URL placeholders."
        )


def render_delivery(
    template: TemplateData,
    context: TemplateContext,
    response_urls: ResponseURLs,
) -> RenderedDelivery:
    """Render one deterministic Delivery snapshot without persistence or I/O."""

    if not isinstance(template, TemplateData):
        raise TypeError("template must be TemplateData")
    if not isinstance(context, TemplateContext):
        raise TypeError("context must be TemplateContext")
    if not isinstance(response_urls, ResponseURLs):
        raise TypeError("response_urls must be ResponseURLs")

    for source in (template.subject_template, template.body_markdown):
        _reject_reserved_markers(source)
        validate_template_variables(source)

    raw_values = {name: getattr(context, name) for name in ALLOWED_TEMPLATE_VARIABLES}
    if any(
        marker in value
        for value in raw_values.values()
        for marker in RESPONSE_URL_PLACEHOLDERS
    ):
        raise TemplateValidationError(
            "Template values cannot contain reserved response URL placeholders."
        )

    subject = _render_variables(template.subject_template, raw_values)
    if _contains_header_control(subject):
        raise TemplateValidationError(
            "Rendered subject cannot contain header control characters."
        )

    markdown_values = {
        name: _escape_markdown_data(value) for name, value in raw_values.items()
    }
    markdown = _render_variables(template.body_markdown, markdown_values)
    author_html = _MARKDOWN.render(markdown)
    sanitized_html = bleach.clean(
        author_html,
        tags=_ALLOWED_HTML_TAGS,
        attributes=_ALLOWED_HTML_ATTRIBUTES,
        protocols=_ALLOWED_HTML_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    _reject_reserved_markers(sanitized_html)

    accepted_url = escape(response_urls.accepted_url, quote=True)
    declined_url = escape(response_urls.declined_url, quote=True)
    accepted_label = escape(template.accepted_label, quote=False)
    declined_label = escape(template.declined_label, quote=False)
    cta_html = (
        '<div data-fmg-system-cta="true">'
        f'<a href="{accepted_url}">{accepted_label}</a> '
        f'<a href="{declined_url}">{declined_label}</a>'
        "</div>"
    )
    separator = "\n" if sanitized_html else ""
    return RenderedDelivery(
        subject=subject,
        markdown=markdown,
        html=f"{sanitized_html}{separator}{cta_html}",
    )


__all__ = [
    "ACCEPTED_RESPONSE_URL_PLACEHOLDER",
    "ALLOWED_TEMPLATE_VARIABLES",
    "DEFAULT_ACCEPTED_LABEL",
    "DEFAULT_DECLINED_LABEL",
    "DECLINED_RESPONSE_URL_PLACEHOLDER",
    "TemplateValidationError",
    "render_delivery",
    "validate_template_variables",
]
