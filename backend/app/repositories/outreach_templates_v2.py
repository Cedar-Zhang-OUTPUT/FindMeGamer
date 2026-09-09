from sqlalchemy import select

from app.api.routes.activity import _get, _error
from app.db.models.outreach_drafts import OutreachTemplateVersion
from app.db.models.profiles import GameProfile
from app.outreach.locked_templates import canonical_template
from app.schemas.outreach_drafts import TemplateVersionView, BuiltinTemplate
from app.db.models.settings import SharedSettings
from app.repositories.library_v2 import game_detail
from app.outreach.game_template import game_template


def game_builtin(session, game):
    settings = session.scalar(select(SharedSettings))
    state = (settings.service_connection_state if settings else {}) or {}
    sender_name = state.get("smtp", {}).get("from_name")
    return BuiltinTemplate.model_validate(
        game_template(
            game_detail(game).model_dump(mode="json"), sender_name=sender_name
        )
    ).model_dump(mode="json")


def builtin():
    spec = canonical_template()
    return BuiltinTemplate(
        name=spec["name"],
        subject=spec["subject"],
        fixed_fragments=spec["fixed_fragments"],
        fixed_hash=spec["fixed_hash"],
        source_metadata={
            "kind": "canonical",
            "document_id": spec["source_document_id"],
            "revision": spec["source_revision"],
            "steam_app_id": spec["source_steam_app_id"],
            "raw_hash": spec["raw_hash"],
        },
    ).model_dump(mode="json")


def template_view(item):
    return TemplateVersionView.model_validate(
        {
            key: getattr(item, key)
            for key in (
                "id",
                "game_id",
                "created_at",
                "name",
                "subject",
                "fixed_fragments",
                "fixed_hash",
                "source_metadata",
            )
        }
    ).model_dump(mode="json")


def register_canonical(session, game_id):
    game = _get(session, GameProfile, game_id)
    source = game_builtin(session, game)
    key = source["fixed_hash"]
    old = session.scalar(
        select(OutreachTemplateVersion).where(
            OutreachTemplateVersion.game_id == game_id,
            OutreachTemplateVersion.builtin_key == key,
        )
    )
    if old:
        return template_view(old)
    item = OutreachTemplateVersion(
        game_id=game_id,
        builtin_key=key,
        **{
            key: source[key]
            for key in (
                "name",
                "subject",
                "fixed_fragments",
                "fixed_hash",
                "source_metadata",
            )
        },
    )
    session.add(item)
    session.flush()
    return template_view(item)


def create_version(session, value):
    raise _error(
        422,
        "template_creation_disabled",
        "Use the shared game-bound outreach template. Historical versions remain readable.",
    )
