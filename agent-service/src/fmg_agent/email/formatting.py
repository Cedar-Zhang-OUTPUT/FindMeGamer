"""Explicit, bounded inline formatting with escaped HTML and a text alternative."""

from html import escape
import re

# Deliberately small syntax: bold, highlight and strikethrough, including nesting.
INLINE = re.compile(r"(\*\*|==|~~)(?=\S)(.+?)(?<=\S)\1")
TAGS = {
    "**": ("<strong>", "</strong>"),
    "==": ('<span style="background-color:#fff2cc;color:#000000">', "</span>"),
    "~~": ("<s>", "</s>"),
}


def inline(text, depth=0):
    if depth >= 8:
        return text, escape(text)
    plain, html, offset = [], [], 0
    for match in INLINE.finditer(text):
        prefix = text[offset : match.start()]
        plain.append(prefix)
        html.append(escape(prefix))
        child_text, child_html = inline(match.group(2), depth + 1)
        opening, closing = TAGS[match.group(1)]
        plain.append(child_text)
        html.append(opening + child_html + closing)
        offset = match.end()
    plain.append(text[offset:])
    html.append(escape(text[offset:]))
    return "".join(plain), "".join(html)


def format_body(message, body_format="plain_text"):
    if body_format == "plain_text":
        return message
    if body_format != "markdown":
        raise ValueError("Unsupported body format")
    source = message["text"]
    text, html = inline(source)
    if message.get("format") == "signature_image":
        return {
            **message,
            "body_format": "markdown",
            "markdown": source,
            "text": text,
            "html": message["html"].replace(
                escape(source).replace("\n", "<br>\n"), html.replace("\n", "<br>\n"), 1
            ),
        }
    return {
        **message,
        "format": "rich_text",
        "body_format": "markdown",
        "markdown": source,
        "text": text,
        "html": '<!doctype html><html><body><div style="font-family:Arial,sans-serif;font-size:14px;line-height:1.5">'
        + html.replace("\n", "<br>\n")
        + "</div></body></html>",
    }
