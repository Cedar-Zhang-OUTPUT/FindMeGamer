"""New campaign drafts are text-only; historical MIME remains reproducible."""

import pytest

from fmg_agent.email.mime import build_message
from fmg_agent.email.templates import get_template, render_template
from test_liminal_fixed_copy import personalization


@pytest.mark.parametrize(
    "template_id,old_version,footer,image_count",
    [
        ("liminal-private-outreach", "1", "liminal-within.png", 2),
        ("thieves-outreach", "2", "thieves-banner.jpg", 1),
    ],
)
def test_image_removal_preserves_text_and_frozen_old_mime(
    template_id, old_version, footer, image_count
):
    current = get_template(template_id)
    historical = dict(
        current, version=old_version, format="signature_image", footer_image=footer
    )
    frozen = render_template(historical, personalization())
    rendered = render_template(current, personalization())
    assert rendered == {
        "subject": frozen["subject"],
        "text": frozen["text"],
        "format": "plain_text",
    }
    envelope = {
        "from": "publisher@example.com",
        "to": "test@example.com",
        "_smtp_date": "Thu, 22 Oct 2026 12:00:00 +0800",
    }
    old_bytes = build_message(dict(frozen, **envelope), "historical").as_bytes()
    new_mail = build_message(dict(rendered, **envelope), "new-draft")
    assert new_mail.get_content_type() == "text/plain"
    assert list(new_mail.iter_attachments()) == []
    assert not new_mail.is_multipart()
    assert new_mail.get_content().rstrip() == rendered["text"]
    assert (
        sum(
            part.get_content_maintype() == "image"
            for part in build_message(dict(frozen, **envelope), "historical").walk()
        )
        == image_count
    )
    assert build_message(dict(frozen, **envelope), "historical").as_bytes() == old_bytes
