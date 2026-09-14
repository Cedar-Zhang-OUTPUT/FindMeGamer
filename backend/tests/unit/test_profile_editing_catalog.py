from uuid import uuid4

from app.db.models.profiles import CreatorProfile, GameProfile


def test_edit_value_has_named_nullable_wire_schema_for_swift():
    from app.schemas.profile_editing import ProfileEditField

    schema = ProfileEditField.model_json_schema()
    assert schema["properties"]["source_value"]["anyOf"] == [
        {"$ref": "#/$defs/EditValue"},
        {"type": "null"},
    ]


def test_catalog_preserves_unavailable_and_protects_identity():
    from app.services.profile_editing import edit_document

    game = GameProfile(
        id=uuid4(), current_facts={"name": "Source"}, analysis={}, brief={}
    )
    fields = {field.key: field for field in edit_document(game).fields}
    assert fields["facts.name"].required
    assert fields["analysis.themes"].value == []
    assert fields["analysis.themes"].source_value is None
    assert "facts.steam_app_id" not in fields
    assert "analysis.confidence" not in fields
    creator = CreatorProfile(
        id=uuid4(), current_facts={"title": "Source"}, analysis={}, brief={}
    )
    creator_fields = {field.key: field for field in edit_document(creator).fields}
    assert creator_fields["analysis.audience_inference.likely_regions"].kind == "list"
    assert "facts.youtube_channel_id" not in creator_fields


def test_effective_projection_does_not_reuse_source_evidence():
    from app.services.profile_editing import effective_section

    profile = GameProfile(
        id=uuid4(),
        current_facts={},
        analysis={
            "themes": {
                "status": "available",
                "values": ["Old"],
                "confidence": "high",
                "evidence": [{"reference": "steam.name"}],
            }
        },
        brief={},
    )
    profile.manual_overrides = {"analysis.themes": ["Human theme"]}
    assert effective_section(profile, "analysis")["themes"] == {
        "status": "available",
        "values": ["Human theme"],
        "provenance": "manual",
    }
    assert profile.analysis["themes"]["values"] == ["Old"]
