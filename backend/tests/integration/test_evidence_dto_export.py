"""Optional export of real serialized synthetic responses for desktop contract QA."""
import json
import os
from pathlib import Path

from tests.integration.test_activity_qualification import ready_composition, preview
from tests.integration.test_outreach_drafts import get_compose


def test_real_serialized_evidence_dtos(auth_client, session, monkeypatch):
    activity, composition = ready_composition(auth_client, session, monkeypatch, count=3)
    composition = get_compose(auth_client, composition["id"])
    qualification = preview(auth_client, composition).json()
    draft = composition["drafts"][0]
    assert draft["input"]["work"]["evidence_tier"] == "related_content"
    assert draft["input"]["work"]["game_id"] is None
    assert draft["input"]["work"]["relation"] == "related_content"
    assert draft["input"]["work"]["evidence_status"] == "recorded_evidence"
    assert not qualification["send_ready"]
    unverified = composition["drafts"][2]
    assert unverified["input"]["work"]["evidence_tier"] == "unverified"
    assert unverified["input"]["work"]["evidence_excerpt"] is None
    destination = os.environ.get("FMG_DTO_EXPORT_DIR")
    if destination:
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        for name, value in {"composition": composition, "draft": draft, "unverified-draft": unverified, "qualification": qualification}.items():
            (directory / (name + ".json")).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
