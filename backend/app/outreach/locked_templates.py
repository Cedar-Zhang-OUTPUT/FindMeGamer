"""Deterministic fixed-fragment rendering, separate from legacy CTA templates."""

import hashlib
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from app.schemas.outreach_drafts import DraftSlotValues, SlotValues

SLOT_KEYS = ("firstName", "channelName", "reference", "observation")
CANONICAL_RAW_HASH = "6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd"
CANONICAL_FIXED_HASH = (
    "0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93"
)
MARKED_SLOT = re.compile(
    r'<span background-color="rgba\(255,246,122,0\.8\)">.*?</span>', re.DOTALL
)


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class _FixedHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.slots = 0

    def handle_starttag(self, tag, attrs):
        if tag not in {"p", "b", "strong", "em", "i", "a", "br"}:
            raise ValueError("Unsupported fixed HTML tag.")
        for name, value in attrs:
            if tag != "a" or name not in {"href", "title"}:
                raise ValueError("Unsupported fixed HTML attribute.")
            if name == "href" and (
                not value or urlsplit(value).scheme not in {"https", "http"}
            ):
                raise ValueError("Fixed links require HTTP or HTTPS.")
        if tag != "br":
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag == "slot" and not attrs:
            self.slots += 1
            return
        self.handle_starttag(tag, attrs)
        if tag != "br":
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            raise ValueError("Fixed HTML tags must be balanced.")

    def handle_comment(self, data):
        raise ValueError("Fixed HTML comments are not supported.")

    def handle_decl(self, decl):
        raise ValueError("Fixed HTML declarations are not supported.")

    def handle_pi(self, data):
        raise ValueError("Fixed HTML instructions are not supported.")


def validate_fixed_template(subject, fragments):
    if (
        not isinstance(subject, str)
        or not subject.strip()
        or len(subject) > 998
        or re.search(r"[\x00-\x1f\x7f]", subject)
    ):
        raise ValueError("A single-line subject is required.")
    if len(fragments) != 5 or any(not isinstance(v, str) for v in fragments):
        raise ValueError("Exactly five fixed fragments define four slots.")
    body = "<slot/>".join(fragments)
    if len(body) > 100_000 or "{{" in body or "}}" in body:
        raise ValueError("Unsupported fixed template size or variables.")
    parser = _FixedHTML()
    parser.feed(body)
    parser.close()
    if parser.stack or parser.slots != 4:
        raise ValueError("Place exactly four slots in HTML text, not attributes.")
    return _hash(subject + "\n" + body)


def canonical_template():
    resource = Path(__file__).with_name("resources") / "liminal-revision-69.json"
    xml = json.loads(resource.read_text(encoding="utf-8"))["content"]
    if _hash(xml) != CANONICAL_RAW_HASH:
        raise ValueError("Canonical source hash mismatch.")
    clean = re.sub(r' id="[^"]*"', "", xml)
    clean = re.sub(r"<title>.*?</title>", "", clean, count=1, flags=re.DOTALL)
    subject_match = re.match(r"<p><b>Subject:</b> (.*?)</p>", clean, re.DOTALL)
    if subject_match is None:
        raise ValueError("Canonical subject is missing.")
    subject, body = subject_match.group(1), clean[subject_match.end() :]
    fragments = MARKED_SLOT.split(body)
    fixed_hash = validate_fixed_template(subject, fragments)
    if fixed_hash != CANONICAL_FIXED_HASH:
        raise ValueError("Canonical fixed content hash mismatch.")
    return {
        "name": "LIMINAL: Within · original locked",
        "subject": subject,
        "fixed_fragments": fragments,
        "fixed_hash": fixed_hash,
        "raw_hash": CANONICAL_RAW_HASH,
        "source_revision": 69,
        "source_steam_app_id": "4952700",
        "source_document_id": "Ieqid5pULoUSqMxOtKTc156xnLe",
    }


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "p":
            self.parts.append("\n")


def render_locked(subject, fragments, values, expected_hash):
    values = SlotValues.model_validate(values).model_dump()
    return render_preview(subject, fragments, values, expected_hash)


def render_preview(subject, fragments, values, expected_hash):
    """Safe incomplete preview, not proof of send eligibility."""
    fixed_hash = validate_fixed_template(subject, fragments)
    if fixed_hash != expected_hash:
        raise ValueError("Fixed template content changed.")
    values = DraftSlotValues.model_validate(values).model_dump()
    pieces = [fragments[0]]
    for key, fragment in zip(SLOT_KEYS, fragments[1:]):
        pieces.extend(
            [
                '<span background-color="rgba(255,246,122,0.8)">',
                escape(values[key]),
                "</span>",
                fragment,
            ]
        )
    html = "".join(pieces)
    if _hash(subject + "\n" + MARKED_SLOT.sub("<slot/>", html)) != fixed_hash:
        raise ValueError("Rendered fixed content changed.")
    parser = _PlainText()
    parser.feed(html)
    parser.close()
    return {
        "subject": subject,
        "html": html,
        "text": "".join(parser.parts).strip(),
        "fixed_hash": fixed_hash,
    }
