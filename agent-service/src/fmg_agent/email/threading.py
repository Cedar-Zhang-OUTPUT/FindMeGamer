"""Untrusted inbound headers normalized for safe, standards-based replies."""

import re
from email.utils import getaddresses

ID = re.compile(r"<[\x21-\x3b\x3d\x3f-\x7e]+@[\x21-\x3b\x3d\x3f-\x7e]+>")


def message_ids(value):
    # Extract only bounded ASCII msg-ids; never propagate raw header text.
    return list(dict.fromkeys(v for v in ID.findall(str(value)) if len(v) <= 500))[-40:]


def valid_message_id(value):
    return isinstance(value, str) and len(value) <= 500 and ID.fullmatch(value)


def read_thread_headers(message):
    from .sending import email_address

    mids = message.get_all("Message-ID", [])
    mid = str(mids[0]).strip() if len(mids) == 1 else ""
    addresses = []
    invalid = False
    try:
        parsed = getaddresses([str(v) for v in message.get_all("Reply-To", [])])
    except ValueError:
        parsed, invalid = [], True
    for _, address in parsed:
        try:
            addresses.append(email_address(address))
        except ValueError:
            invalid = True
    return {
        "message_id": mid if valid_message_id(mid) else None,
        "in_reply_to": message_ids(message.get("In-Reply-To", "")),
        "references": message_ids(message.get("References", "")),
        "reply_to": list(dict.fromkeys(addresses)),
        "reply_to_invalid": invalid,
    }


def reply_subject(subject):
    subject = re.sub(r"[\x00-\x1f\x7f]+", " ", subject).strip()
    return subject if re.match(r"(?i)^re\s*:", subject) else "Re: " + subject


def reply_references(headers):
    refs = headers.get("references") or headers.get("in_reply_to") or []
    refs = [v for v in refs if valid_message_id(v)]
    refs = list(dict.fromkeys(v for v in refs if v != headers["message_id"])) + [
        headers["message_id"]
    ]
    # Keep the root plus the recent chain and immediate parent within a bound.
    refs = refs[:1] + refs[-19:] if len(refs) > 20 else refs
    while len(" ".join(refs)) > 7000 and len(refs) > 2:
        del refs[1]
    return refs
