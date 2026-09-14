import importlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError


def contract():
    assert importlib.util.find_spec(
        "app.schemas.creator_import"
    ), "curated contract missing"
    return importlib.import_module("app.schemas.creator_import").CreatorImport


def test_curated_freshness_keeps_strict_thirty_day_boundary():
    from datetime import timedelta
    from types import SimpleNamespace
    from app.services.profile_source_visibility import curated_source_is_expired

    now = datetime.now(UTC)
    profile = SimpleNamespace(
        platform="twitch", last_analyzed_at=now - timedelta(days=30)
    )
    assert not curated_source_is_expired(profile, now=now)
    profile.last_analyzed_at -= timedelta(microseconds=1)
    assert curated_source_is_expired(profile, now=now)


def record(platform="twitch"):
    host = "twitch.tv" if platform == "twitch" else "instagram.com"
    return dict(
        platform=platform,
        platform_account_id="990000001",
        account_id_source_url=f"https://www.{host}/synthetic_fixture",
        profile_url=f"https://www.{host}/synthetic_fixture",
        username="synthetic_fixture",
        display_name="Synthetic fixture (not a real creator)",
        collected_at="2026-09-14T10:00:00Z",
        followers_precision="unknown",
    )


def supplied_analysis(now=None):
    """Separately prepared synthetic common analysis, not an importer transform."""
    from tests.unit.analysis.test_ai_schemas import creator_synthesis_payload

    payload = creator_synthesis_payload()

    def bind(value):
        if isinstance(value, dict):
            if "reference" in value and "kind" in value:
                value.update(reference="profile", source_type="public_link")
            for child in value.values():
                bind(child)
        elif isinstance(value, list):
            for child in value:
                bind(child)

    bind(payload)
    for field in ("public_email", "linked_site", "social_links"):
        payload[field] = {
            "status": "unavailable",
            "reason": "No contacts in this synthetic fixture.",
        }
    return {"analyzed_at": (now or datetime.now(UTC)).isoformat(), "synthesis": payload}


def test_collection_normalizes_without_dropping_facts():
    raw = record()
    raw.update(
        platform_account_id=None,
        account_id_source_url=None,
        collection_notes="Synthetic test collection.",
    )
    parsed = contract().model_validate(
        {"collection_schema_version": 1, "creators": [raw]}
    )
    assert parsed.records[0].platform_account_id is None
    assert parsed.records[0].collection_notes == "Synthetic test collection."
    assert parsed.records[0].analysis is None
    assert contract().model_validate_json(parsed.model_dump_json()) == parsed


def test_instagram_provisional_identity_is_bound_to_username_without_fake_source():
    raw = record("instagram")
    raw.update(platform_account_id="ig-synthetic_fixture", account_id_source_url=None)
    parsed = contract().model_validate({"schema_version": 1, "records": [raw]})
    assert parsed.records[0].platform_account_id == "ig-synthetic_fixture"
    assert parsed.records[0].account_id_source_url is None
    assert contract().model_validate_json(parsed.model_dump_json()) == parsed


@pytest.mark.parametrize(
    "change",
    [
        {"platform_account_id": "ig-another_account"},
        {"account_id_source_url": "https://www.instagram.com/synthetic_fixture"},
        {
            "platform": "twitch",
            "profile_url": "https://www.twitch.tv/synthetic_fixture",
        },
    ],
)
def test_provisional_identity_cannot_impersonate_another_account_or_verified_id(change):
    raw = record("instagram")
    raw.update(platform_account_id="ig-synthetic_fixture", account_id_source_url=None)
    raw.update(change)
    with pytest.raises(ValidationError):
        contract().model_validate({"schema_version": 1, "records": [raw]})


def test_collected_works_metrics_and_observations_survive_roundtrip():
    raw = record()
    raw["works"] = [
        {
            "work_id": "work-001",
            "platform_content_id": "990000002",
            "url": "https://www.twitch.tv/videos/990000002",
            "kind": "vod",
            "title_original": "Synthetic puzzle fixture",
            "published_at": "2026-09-13T10:00:00Z",
            "game_names": ["Synthetic Puzzle"],
            "metrics": [
                {
                    "name": "vod_views",
                    "value": 42,
                    "precision": "exact",
                    "observed_at": raw["collected_at"],
                }
            ],
        }
    ]
    raw["observations"] = [
        {
            "work_id": "work-001",
            "basis": "metadata_only",
            "observation_en": "The supplied synthetic title names a puzzle.",
            "source_url": raw["works"][0]["url"],
            "observed_at": raw["collected_at"],
        }
    ]
    parsed = contract().model_validate(
        {"collection_schema_version": 1, "creators": [raw]}
    )
    restored = contract().model_validate_json(parsed.model_dump_json()).records[0]
    assert restored.works[0].title_original == "Synthetic puzzle fixture"
    assert restored.works[0].metrics[0].value == 42
    assert restored.observations[0].basis == "metadata_only"
    assert restored.analysis is None
    raw["observations"][0]["source_url"] = "https://www.twitch.tv/videos/another"
    with pytest.raises(ValidationError, match="supplied work URL"):
        contract().model_validate({"collection_schema_version": 1, "creators": [raw]})


@pytest.mark.parametrize(
    "change",
    [
        {"profile_url": "https://www.instagram.com/synthetic_fixture"},
        {"username": "another_account"},
        {"platform_account_id": "synthetic_fixture"},
        {"account_id_source_url": None},
        {"access_token": "DO-NOT-LOG-THIS"},
        {
            "profile_url": "https://www.twitch.tv/synthetic_fixture?access_token=DO-NOT-LOG-THIS"
        },
        {"collected_at": "2026-09-14T10:00:00"},
    ],
)
def test_rejects_identity_and_secret_mistakes(change):
    raw = record()
    raw.update(change)
    with pytest.raises(ValidationError):
        contract().model_validate({"schema_version": 1, "records": [raw]})


def test_rejects_duplicate_contact_noise():
    raw = record()
    contact = dict(
        email="business@example.com",
        purpose="Business inquiries",
        source_url="https://example.com/contact",
        observed_at=raw["collected_at"],
    )
    raw["contacts"] = [contact, {**contact, "email": "BUSINESS@example.com"}]
    with pytest.raises(ValidationError):
        contract().model_validate({"schema_version": 1, "records": [raw]})


def test_examples_and_filled_collection_templates():
    root = (
        Path("/contract-docs")
        if Path("/contract-docs").exists()
        else Path(__file__).resolve().parents[3] / "docs/creator-import"
    )
    for platform in ("twitch", "instagram"):
        parsed = contract().model_validate_json(
            (root / f"{platform}.example.json").read_text()
        )
        assert parsed.records[0].platform == platform
        template = json.loads(
            (root / f"{platform}.collection-template.json").read_text()
        )
        template["creators"][0].update(record(platform), works=[], observations=[])
        assert (
            contract()
            .model_validate(template)
            .records[0]
            .display_name.startswith("Synthetic")
        )


@pytest.mark.parametrize(
    "reference", ["video:another-account", "work:missing", "observation:missing"]
)
def test_analysis_rejects_unbound_evidence(reference):
    raw = record()
    raw["analysis"] = supplied_analysis()
    raw["analysis"]["synthesis"]["creator_brief"]["positioning"]["evidence"][0][
        "reference"
    ] = reference
    with pytest.raises(ValidationError, match="bound"):
        contract().model_validate({"schema_version": 1, "records": [raw]})


def test_cli_offline_dry_run_and_secret_safe_error(tmp_path, capsys, monkeypatch):
    from app.cli.import_creator_profiles import main

    monkeypatch.setenv("DATABASE_URL", "unusable-offline-database")
    path = tmp_path / "collection.json"
    raw = record()
    raw.update(platform_account_id=None, account_id_source_url=None)
    path.write_text(json.dumps({"collection_schema_version": 1, "creators": [raw]}))
    assert main(["--file", str(path), "--dry-run"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["records"][0]["status"] == "needs_identity_resolution"
    assert report["records"][0]["analysis_available"] is False
    raw["access_token"] = "SECRET-THAT-MUST-NOT-BE-ECHOED"
    path.write_text(json.dumps({"schema_version": 1, "records": [raw]}))
    assert main(["--file", str(path), "--dry-run"]) == 2
    captured = capsys.readouterr()
    assert "SECRET-THAT-MUST-NOT-BE-ECHOED" not in captured.err + captured.out
