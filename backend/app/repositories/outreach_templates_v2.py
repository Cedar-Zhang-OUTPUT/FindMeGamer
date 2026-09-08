from sqlalchemy import select

from app.api.routes.activity import _get, _error
from app.core.idempotency import request_hash
from app.db.models.outreach_drafts import OutreachTemplateVersion
from app.db.models.profiles import GameProfile
from app.outreach.locked_templates import canonical_template, validate_fixed_template
from app.schemas.outreach_drafts import TemplateVersionView, BuiltinTemplate


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
    if game.steam_app_id and game.steam_app_id != "4952700":
        raise _error(
            422,
            "template_game_mismatch",
            "The original template is for LIMINAL: Within, not this Steam game.",
        )
    key = "liminal-revision-69"
    old = session.scalar(
        select(OutreachTemplateVersion).where(
            OutreachTemplateVersion.game_id == game_id,
            OutreachTemplateVersion.builtin_key == key,
        )
    )
    if old:
        return template_view(old)
    source = builtin()
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
    _get(session, GameProfile, value.game_id)
    digest = request_hash(
        method="POST",
        path="/api/v2/outreach/template-versions",
        canonical_request=value.model_dump(mode="json"),
    )
    old = session.scalar(
        select(OutreachTemplateVersion).where(
            OutreachTemplateVersion.request_id == value.request_id
        )
    )
    if old:
        if old.request_hash != digest:
            raise _error(
                409,
                "template_version_request_conflict",
                "This request ID already belongs to another template version.",
            )
        return template_view(old)
    try:
        fixed_hash = validate_fixed_template(value.subject, value.fixed_fragments)
    except ValueError:
        raise _error(
            422,
            "template_fixed_content_invalid",
            "Use five safe fixed fragments with four text slots and a single-line subject.",
        ) from None
    item = OutreachTemplateVersion(
        game_id=value.game_id,
        request_id=value.request_id,
        request_hash=digest,
        name=value.name,
        subject=value.subject,
        fixed_fragments=value.fixed_fragments,
        fixed_hash=fixed_hash,
        source_metadata={"kind": "user_saved"},
    )
    session.add(item)
    session.flush()
    return template_view(item)
