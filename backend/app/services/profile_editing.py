"""Explicit editorial catalog, projection and manual Match context.

Source analysis is never rewritten or validated as a human claim. A projection
replaces the whole claim and deliberately drops its evidence and confidence.
"""

from copy import deepcopy
from dataclasses import dataclass

from app.core.errors import APIError
from app.db.models.profiles import CreatorProfile, GameProfile
from app.services.profile_source_visibility import _creator_youtube_is_stale
from app.schemas.profile_editing import (
    ProfileEditDocument,
    ProfileEditField,
    ProfileEditPatch,
)


@dataclass(frozen=True)
class EditableField:
    key: str
    kind: str
    required: bool = False


def _fields(section, kind, names):
    return tuple(EditableField(f"{section}.{name}", kind) for name in names.split())


# Names mirror SteamGameSource, CreatorSource and the final synthesis/Brief
# schemas. Metrics, acquisition identity, contacts and diagnostics are excluded.
GAME_FIELDS = (
    EditableField("facts.name", "text", True),
    *_fields("facts", "text", "type release_date supported_languages"),
    *_fields(
        "facts", "multiline", "short_description detailed_description about_the_game"
    ),
    *_fields("facts", "list", "developers publishers genres categories platforms"),
    *_fields("analysis", "multiline", "short_summary core_gameplay_loop visual_style"),
    *_fields(
        "analysis",
        "list",
        "themes tone target_audience key_selling_points content_hooks comparable_games suitable_creator_types promotion_risks",
    ),
    *_fields(
        "brief", "multiline", "positioning_premise core_gameplay_loop visual_identity"
    ),
    *_fields(
        "brief",
        "list",
        "genres themes tone target_audience key_selling_points content_hooks comparable_games suitable_creator_types promotion_risks",
    ),
)
CREATOR_FIELDS = (
    EditableField("facts.title", "text", True),
    *_fields("facts", "text", "country"),
    *_fields("facts", "multiline", "description"),
    *_fields(
        "analysis",
        "multiline",
        "content_summary pacing production_quality livestream_tendency long_form_tendency short_form_tendency recent_performance_summary engagement_summary publishing_frequency_context audience_inference.primary_language",
    ),
    *_fields(
        "analysis",
        "list",
        "primary_games genres formats style representative_video_context sponsorship_patterns brand_safety suitable_game_types collaboration_risks audience_inference.likely_regions audience_inference.interests",
    ),
    *_fields(
        "brief",
        "multiline",
        "positioning style_and_pacing audience performance_context promotion_fit brand_safety",
    ),
    *_fields(
        "brief", "list", "content_focus formats suitable_game_types collaboration_risks"
    ),
)


def catalog(profile):
    return GAME_FIELDS if isinstance(profile, GameProfile) else CREATOR_FIELDS


def _source_value(profile, field):
    if isinstance(profile, CreatorProfile) and _creator_youtube_is_stale(
        profile.source_status
    ):
        return None
    section, *path = field.key.split(".")
    value = getattr(profile, "current_facts" if section == "facts" else section) or {}
    for component in path:
        value = value.get(component) if isinstance(value, dict) else None
    if isinstance(value, dict):
        value = value.get("values" if field.kind == "list" else "value")
    if field.kind == "list":
        return (
            deepcopy(value)
            if isinstance(value, list) and all(isinstance(item, str) for item in value)
            else None
        )
    return value if isinstance(value, str) else None


def edit_document(profile):
    overrides = profile.manual_overrides or {}
    return ProfileEditDocument(
        profile_type="game" if isinstance(profile, GameProfile) else "creator",
        profile_id=profile.id,
        revision=profile.profile_revision or 0,
        fields=[
            ProfileEditField(
                key=field.key,
                section=field.key.split(".")[0],
                label=field.key.split(".")[-1].replace("_", " ").capitalize(),
                kind=field.kind,
                required=field.required,
                value=overrides.get(
                    field.key,
                    _source_value(profile, field)
                    or ([] if field.kind == "list" else ""),
                ),
                source_value=_source_value(profile, field),
                is_overridden=field.key in overrides,
            )
            for field in catalog(profile)
        ],
    )


def apply_edit(profile, patch: ProfileEditPatch):
    fields = {field.key: field for field in catalog(profile)}
    invalid = set(patch.changes) | set(patch.reset_fields)
    if (
        invalid - fields.keys()
        or set(patch.changes) & set(patch.reset_fields)
        or len(set(patch.reset_fields)) != len(patch.reset_fields)
    ):
        raise APIError(
            status_code=422,
            code="profile_edit_invalid",
            message="Choose editable fields and use either a change or reset for each field.",
        )
    for key, value in patch.changes.items():
        field = fields[key]
        if (field.kind == "list") != isinstance(value, list) or (
            field.required and (not isinstance(value, str) or not value.strip())
        ):
            raise APIError(
                status_code=422,
                code="profile_edit_invalid",
                message="Check required values and field types before saving.",
            )
    if patch.expected_revision != (profile.profile_revision or 0):
        raise APIError(
            status_code=409,
            code="profile_revision_conflict",
            message="This profile changed. Reload and review your draft before saving again.",
        )
    overrides = deepcopy(profile.manual_overrides or {})
    for key in patch.reset_fields:
        overrides.pop(key, None)
    overrides.update(deepcopy(patch.changes))
    profile.manual_overrides = overrides
    profile.profile_revision = (profile.profile_revision or 0) + 1
    return edit_document(profile)


def effective_section(profile, section, *, source_visible=True):
    source = getattr(profile, "current_facts" if section == "facts" else section) or {}
    result = deepcopy(source) if source_visible else {}
    for field in catalog(profile):
        if not field.key.startswith(section + ".") or field.key not in (
            profile.manual_overrides or {}
        ):
            continue
        value = deepcopy(profile.manual_overrides[field.key])
        if section != "facts":
            value = {
                "status": "available",
                "values" if field.kind == "list" else "value": value,
                "provenance": "manual",
            }
        target = result
        path = field.key.split(".")[1:]
        for key in path[:-1]:
            if not isinstance(target.get(key), dict):
                target[key] = {}
            target = target[key]
        target[path[-1]] = value
    return result


def effective_name(profile):
    key = "facts.name" if isinstance(profile, GameProfile) else "facts.title"
    return (profile.manual_overrides or {}).get(key, profile.sort_name)


def manual_context(profile):
    return {
        "revision": profile.profile_revision or 0,
        "provenance": "manual",
        "overrides": deepcopy(profile.manual_overrides or {}),
    }
