"""One fixed structure, with source-bound game facts and four creator slots."""

from html import escape

from app.discovery.evaluation_snapshot import digest
from app.outreach.locked_templates import validate_fixed_template

KEY = "game-outreach-v1"


def game_template(game, *, sender_name=None):
    name = game.get("name") or "our game"
    title = " ".join(name.split())
    subject = f"Thought you might enjoy {title}"
    paragraphs = [
        f"<p>I’m reaching out because I’d love to invite you to try our game, <b>{escape(name)}</b>.</p>"
    ]
    url = game.get("website_url")
    if url:
        paragraphs.append(
            f'<p>Game: <a href="{escape(url, quote=True)}">{escape(url)}</a></p>'
        )
    if game.get("description"):
        paragraphs.append(f'<p>{escape(game["description"])}</p>')
    # Reference entries are manually maintained Library facts. Never infer a
    # comparison from an AI summary, campaign intent or another game's template.
    for reference in game.get("reference_works", []):
        if not reference.get("name"):
            continue
        details = reference.get("reason") or "; ".join(
            reference.get("similarities", [])
        )
        if details:
            paragraphs.append(
                f'<p>Reference: <b>{escape(reference["name"])}</b> — {escape(details)}</p>'
            )
    paragraphs.extend(
        [
            "<p>If you enjoy the game and think it would be a good fit for your audience, we’d love to see you share it on your channel in whatever format feels natural to you—whether that’s a video, a livestream, or even a short mention. There is absolutely no obligation to cover it, though; we’d simply be happy for you to try it, and any feedback would already mean a lot to us.</p>",
            "<p>Thanks for your time, and for the work you put into your channel.</p>",
            "<p>Best,</p>" + (f"<p>{escape(sender_name)}</p>" if sender_name else ""),
        ]
    )
    introduction = f"I’m {escape(sender_name)}. " if sender_name else ""
    fragments = [
        "<p>Hi ",
        f",</p><p>{introduction}I’ve been following ",
        ", and I especially enjoyed your video on ",
        ". I liked how you ",
        "</p>" + "".join(paragraphs),
    ]
    fixed_hash = validate_fixed_template(subject, fragments)
    return {
        "key": KEY,
        "name": f"{title[:220]} · outreach",
        "subject": subject,
        "fixed_fragments": fragments,
        "fixed_hash": fixed_hash,
        "source_metadata": {
            "kind": "game_bound",
            "revision": 1,
            "game_id": str(game["id"]),
            "game_revision": game.get("revision", 0),
            "game_fingerprint": digest(game),
            "steam_app_id": game.get("steam_app_id"),
            "sender_name": sender_name,
        },
    }
