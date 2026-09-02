from __future__ import annotations

from html.parser import HTMLParser
import logging
from typing import Any

import pytest
from pydantic import ValidationError

from app.db.models.outreach import Template
from app.outreach.templates import (
    ACCEPTED_RESPONSE_URL_PLACEHOLDER,
    ALLOWED_TEMPLATE_VARIABLES,
    DEFAULT_ACCEPTED_LABEL,
    DEFAULT_DECLINED_LABEL,
    DECLINED_RESPONSE_URL_PLACEHOLDER,
    TemplateValidationError,
    render_delivery,
    validate_template_variables,
)
from app.repositories.outreach import template_data_from_row
from app.schemas.outreach import (
    RenderedDelivery,
    ResponseURLs,
    TemplateContext,
    TemplateData,
)


EXPECTED_VARIABLES = {
    "creator_name",
    "channel_name",
    "game_name",
    "steam_url",
    "game_summary",
    "match_reason",
    "sender_name",
}


def template(**overrides: str) -> TemplateData:
    values = {
        "subject_template": "An invitation for {{creator_name}}",
        "body_markdown": "Hello {{creator_name}} from {{sender_name}}.",
        "accepted_label": DEFAULT_ACCEPTED_LABEL,
        "declined_label": DEFAULT_DECLINED_LABEL,
    }
    values.update(overrides)
    return TemplateData(**values)


def context(**overrides: str) -> TemplateContext:
    values = {
        "creator_name": "Avery Creator",
        "channel_name": "Avery Plays",
        "game_name": "Tactical Orchard",
        "steam_url": "https://store.steampowered.com/app/1234",
        "game_summary": "A cooperative strategy game.",
        "match_reason": "Your thoughtful strategy videos fit the game.",
        "sender_name": "Morgan",
    }
    values.update(overrides)
    return TemplateContext(**values)


def urls(**overrides: str) -> ResponseURLs:
    values = {
        "accepted_url": "https://example.invalid/r/preview-accepted",
        "declined_url": "https://example.invalid/r/preview-declined",
    }
    values.update(overrides)
    return ResponseURLs(**values)


class HTMLSummary(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.tag_attributes: list[tuple[str, dict[str, str | None]]] = []
        self.anchor_hrefs: list[str | None] = []
        self.anchor_text: list[str] = []
        self._anchor_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.tag_attributes.append((tag, dict(attrs)))
        if tag == "a":
            self.anchor_hrefs.append(dict(attrs).get("href"))
            self.anchor_text.append("")
            self._anchor_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._anchor_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._anchor_depth:
            self.anchor_text[-1] += data


def summarize_html(value: str) -> HTMLSummary:
    summary = HTMLSummary()
    summary.feed(value)
    return summary


def test_variable_contract_is_exact_and_repeats_deduplicate() -> None:
    text = " ".join(f"{{{{{name}}}}}" for name in sorted(EXPECTED_VARIABLES))
    text += " {{creator_name}} {{creator_name}}"

    assert ALLOWED_TEMPLATE_VARIABLES == frozenset(EXPECTED_VARIABLES)
    assert validate_template_variables(text) == EXPECTED_VARIABLES


def test_all_seven_variables_render_into_subject_and_markdown() -> None:
    rendered = render_delivery(
        template(
            subject_template="{{creator_name}} / {{channel_name}} / {{game_name}}",
            body_markdown=(
                "{{creator_name}}\n\n{{channel_name}}\n\n{{game_name}}\n\n"
                "{{steam_url}}\n\n{{game_summary}}\n\n{{match_reason}}\n\n"
                "{{sender_name}}"
            ),
        ),
        context(),
        urls(),
    )

    assert rendered.subject == ("Avery Creator / Avery Plays / Tactical Orchard")
    for expected in (
        "Avery Creator",
        "Avery Plays",
        "Tactical Orchard",
        "A cooperative strategy game.",
        "Your thoughtful strategy videos fit the game.",
        "Morgan",
    ):
        assert expected in rendered.markdown
        assert expected in rendered.html
    assert "https://store.steampowered.com/app/1234" in rendered.markdown


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("Hello {{unknown_name}}", "unknown_name"),
        ("Hello {{ creator_name }}", "malformed"),
        ("Hello {{creator_name}", "malformed"),
        ("Hello {creator_name}}", "malformed"),
        ("Hello {creator_name}", "malformed"),
        ("Hello {{}}", "malformed"),
        ("Hello {{{creator_name}}", "malformed"),
        ("Hello {{creator_name}}}", "malformed"),
    ],
)
def test_unknown_or_ordinary_malformed_variable_rejects_whole_template(
    source: str,
    message: str,
) -> None:
    with pytest.raises(TemplateValidationError, match=message):
        validate_template_variables(source)

    with pytest.raises(TemplateValidationError, match=message):
        render_delivery(template(body_markdown=source), context(), urls())


def test_substituted_values_remain_text_and_cannot_create_markup_or_links() -> None:
    injected = (
        "**bold** [phish](https://evil.invalid) "
        "<img src=x onerror=alert(1)>\n\n# heading"
    )

    rendered = render_delivery(
        template(
            subject_template="Static subject",
            body_markdown="Creator: {{creator_name}}",
        ),
        context(creator_name=injected),
        urls(),
    )
    summary = summarize_html(rendered.html)

    assert "<img" not in rendered.html
    assert "<strong>bold</strong>" not in rendered.html
    assert "https://evil.invalid" not in summary.anchor_hrefs
    assert summary.anchor_hrefs == [
        "https://example.invalid/r/preview-accepted",
        "https://example.invalid/r/preview-declined",
    ]
    assert "**bold**" in rendered.html
    assert "[phish](https://evil.invalid)" in rendered.html
    assert "# heading" in rendered.html


@pytest.mark.parametrize(
    "injected",
    ["~~~\ncode fence\n~~~", "    indented code"],
)
def test_substituted_values_cannot_create_code_blocks(injected: str) -> None:
    rendered = render_delivery(
        template(subject_template="Static subject", body_markdown="{{game_summary}}"),
        context(game_summary=injected),
        urls(),
    )
    summary = summarize_html(rendered.html)

    assert "code" not in summary.tags
    assert injected.strip().replace("~~~\n", "").replace("\n~~~", "") in rendered.html


@pytest.mark.parametrize(
    "subject_template",
    ["Hello\rBcc: victim@example.com", "Hello\nBcc: victim@example.com", "Bad\x00"],
)
def test_subject_template_rejects_header_injection(subject_template: str) -> None:
    with pytest.raises(TemplateValidationError, match="subject"):
        render_delivery(template(subject_template=subject_template), context(), urls())


@pytest.mark.parametrize(
    "creator_name",
    ["Avery\rBcc: victim@example.com", "Avery\nBcc: victim@example.com", "Avery\x7f"],
)
def test_subject_value_rejects_header_injection(creator_name: str) -> None:
    with pytest.raises(TemplateValidationError, match="subject"):
        render_delivery(template(), context(creator_name=creator_name), urls())


def test_raw_html_scripts_event_attributes_and_unsafe_links_do_not_survive() -> None:
    body = (
        '<script>alert(1)</script><b onclick="alert(2)">raw</b>\n\n'
        "[javascript](javascript:alert(3))\n\n"
        "[data](data:text/html;base64,PHNjcmlwdD4=)\n\n"
        '<a href="https://evil.invalid" onmouseover="alert(4)">raw link</a>'
    )

    rendered = render_delivery(template(body_markdown=body), context(), urls())
    summary = summarize_html(rendered.html)

    assert "<script" not in rendered.html
    assert all(
        not any(name.startswith("on") for name in attributes)
        for _, attributes in summary.tag_attributes
    )
    assert "javascript:" not in summary.anchor_hrefs
    assert not any((href or "").startswith("data:") for href in summary.anchor_hrefs)
    assert "<b" not in rendered.html
    assert summary.anchor_hrefs == [
        "https://example.invalid/r/preview-accepted",
        "https://example.invalid/r/preview-declined",
    ]


def test_allowed_markdown_and_safe_link_protocols_survive_sanitation() -> None:
    body = (
        "Paragraph with **strong**, *emphasis*, and `code`.  \nline break\n\n"
        "> quoted\n\n"
        "- unordered\n\n"
        "1. ordered\n\n"
        "[web](https://example.com/path?q=1) and "
        "[mail](mailto:creator@example.com)"
    )

    rendered = render_delivery(template(body_markdown=body), context(), urls())
    summary = summarize_html(rendered.html)

    for tag in ("p", "br", "strong", "em", "ul", "ol", "li", "blockquote", "code"):
        assert tag in summary.tags
    assert summary.anchor_hrefs[:2] == [
        "https://example.com/path?q=1",
        "mailto:creator@example.com",
    ]
    assert summary.anchor_hrefs[2:] == [
        "https://example.invalid/r/preview-accepted",
        "https://example.invalid/r/preview-declined",
    ]


def test_configurable_labels_are_escaped_inside_one_appended_system_cta() -> None:
    accepted = '<strong onclick="alert(1)">Absolutely & yes</strong>'
    declined = '<img src=x onerror="alert(2)">No thanks'

    rendered = render_delivery(
        template(
            body_markdown="Author-controlled body.",
            accepted_label=accepted,
            declined_label=declined,
        ),
        context(),
        urls(),
    )
    summary = summarize_html(rendered.html)

    assert rendered.html.count('data-fmg-system-cta="true"') == 1
    assert rendered.html.index("Author-controlled body.") < rendered.html.index(
        'data-fmg-system-cta="true"'
    )
    assert summary.anchor_hrefs == [
        "https://example.invalid/r/preview-accepted",
        "https://example.invalid/r/preview-declined",
    ]
    assert summary.anchor_text == [accepted, declined]
    assert rendered.html.count("Absolutely &amp; yes") == 1
    assert "<img" not in rendered.html
    assert all(
        not any(name.startswith("on") for name in attributes)
        for _, attributes in summary.tag_attributes
    )


def test_default_cta_labels_are_exact_english_copy() -> None:
    data = TemplateData(
        subject_template="Hello",
        body_markdown="Body",
    )
    rendered = render_delivery(data, context(), urls())

    assert data.accepted_label == "Yes, I'm in"
    assert data.declined_label == "No, I'm not interested"
    assert DEFAULT_ACCEPTED_LABEL == "Yes, I'm in"
    assert DEFAULT_DECLINED_LABEL == "No, I'm not interested"
    assert DEFAULT_ACCEPTED_LABEL in rendered.html
    assert DEFAULT_DECLINED_LABEL in rendered.html
    assert summarize_html(rendered.html).anchor_text == [
        "Yes, I'm in",
        "No, I'm not interested",
    ]


@pytest.mark.parametrize("field", ["subject_template", "body_markdown"])
@pytest.mark.parametrize(
    "placeholder",
    [ACCEPTED_RESPONSE_URL_PLACEHOLDER, DECLINED_RESPONSE_URL_PLACEHOLDER],
)
def test_reserved_response_placeholders_cannot_be_authored(
    field: str,
    placeholder: str,
) -> None:
    with pytest.raises(TemplateValidationError, match="reserved"):
        render_delivery(template(**{field: placeholder}), context(), urls())


def test_reserved_response_placeholders_are_backend_owned_and_each_occurs_once() -> (
    None
):
    rendered = render_delivery(
        template(),
        context(),
        ResponseURLs(
            accepted_url=ACCEPTED_RESPONSE_URL_PLACEHOLDER,
            declined_url=DECLINED_RESPONSE_URL_PLACEHOLDER,
        ),
    )

    assert rendered.html.count(ACCEPTED_RESPONSE_URL_PLACEHOLDER) == 1
    assert rendered.html.count(DECLINED_RESPONSE_URL_PLACEHOLDER) == 1
    assert summarize_html(rendered.html).anchor_hrefs == [
        ACCEPTED_RESPONSE_URL_PLACEHOLDER,
        DECLINED_RESPONSE_URL_PLACEHOLDER,
    ]


@pytest.mark.parametrize("field", ["accepted_label", "declined_label"])
@pytest.mark.parametrize(
    "placeholder",
    [ACCEPTED_RESPONSE_URL_PLACEHOLDER, DECLINED_RESPONSE_URL_PLACEHOLDER],
)
def test_reserved_response_placeholders_cannot_be_authored_in_cta_labels(
    field: str,
    placeholder: str,
) -> None:
    with pytest.raises(ValidationError, match="reserved"):
        template(**{field: f"Choose {placeholder}"})


@pytest.mark.parametrize(
    "bad_url",
    [
        "javascript:alert(1)",
        "mailto:creator@example.com",
        "ftp://example.com/path",
        "https://user:secret@example.com/path",
        "https://example.com/path#fragment",
        "https://example.com/path\nBcc:test@example.com",
        "https://example.com/path with spaces",
        "https:///missing-host",
        "https://example.com\\ambiguous/path",
    ],
)
def test_response_urls_reject_unsafe_or_ambiguous_values(bad_url: str) -> None:
    with pytest.raises(ValidationError):
        ResponseURLs(
            accepted_url=bad_url,
            declined_url="https://example.invalid/r/declined",
        )


def test_each_response_field_only_accepts_its_exact_reserved_placeholder() -> None:
    with pytest.raises(ValidationError):
        ResponseURLs(
            accepted_url=DECLINED_RESPONSE_URL_PLACEHOLDER,
            declined_url=DECLINED_RESPONSE_URL_PLACEHOLDER,
        )

    with pytest.raises(ValidationError):
        ResponseURLs(
            accepted_url=ACCEPTED_RESPONSE_URL_PLACEHOLDER,
            declined_url=ACCEPTED_RESPONSE_URL_PLACEHOLDER,
        )


@pytest.mark.parametrize(
    ("accepted_label", "declined_label"),
    [("", "No"), ("   ", "No"), ("Yes", "\n"), ("x" * 256, "No")],
)
def test_labels_are_nonempty_plain_text_and_database_length_compatible(
    accepted_label: str,
    declined_label: str,
) -> None:
    with pytest.raises(ValidationError):
        template(accepted_label=accepted_label, declined_label=declined_label)

    assert len(template(accepted_label="x" * 255).accepted_label) == 255


def test_render_contracts_are_closed_immutable_and_reject_missing_context() -> None:
    with pytest.raises(ValidationError):
        TemplateData(
            subject_template="Hello",
            body_markdown="Body",
            unknown="not allowed",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError):
        TemplateContext.model_validate(
            {
                "creator_name": "Avery",
                "channel_name": "Avery Plays",
                "game_name": "Game",
                "steam_url": "https://example.com",
                "game_summary": "Summary",
                "match_reason": "Reason",
            }
        )

    rendered = RenderedDelivery(subject="Subject", markdown="Body", html="<p>Body</p>")
    with pytest.raises(ValidationError):
        rendered.subject = "Changed"


def test_template_row_projects_only_render_data() -> None:
    row = Template(
        name="Creator launch",
        version=3,
        subject_template="Hello {{creator_name}}",
        body_markdown="Body from {{sender_name}}",
        accepted_label="Count me in",
        declined_label="Not this time",
        is_default=True,
    )

    assert template_data_from_row(row) == TemplateData(
        subject_template="Hello {{creator_name}}",
        body_markdown="Body from {{sender_name}}",
        accepted_label="Count me in",
        declined_label="Not this time",
    )


def test_rendering_is_deterministic_and_performs_no_logging_or_io(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def unexpected_io(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("rendering attempted I/O")

    monkeypatch.setattr("builtins.open", unexpected_io)
    monkeypatch.setattr("socket.socket", unexpected_io)
    monkeypatch.setattr("socket.getaddrinfo", unexpected_io)
    caplog.set_level(logging.DEBUG)

    first = render_delivery(template(), context(), urls())
    second = render_delivery(template(), context(), urls())

    assert first == second
    assert not any(record.name.startswith("app.outreach") for record in caplog.records)
    assert not any(
        ACCEPTED_RESPONSE_URL_PLACEHOLDER in record.getMessage()
        or DECLINED_RESPONSE_URL_PLACEHOLDER in record.getMessage()
        for record in caplog.records
    )
