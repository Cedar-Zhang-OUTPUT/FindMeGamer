import json
from uuid import uuid4

import pytest

from app.integrations.errors import InvalidModelOutput
from app.workers import evaluation_tasks


@pytest.mark.parametrize("reason", [
    "evaluation_candidate_id_invalid", "evaluation_work_ids_invalid",
    "evaluation_evidence_invalid", "evaluation_narrative_invalid",
    "deepseek_model_output_invalid",
])
def test_safe_reason_logged_without_changing_public_error(reason, caplog):
    run_id, step_id = uuid4(), uuid4()
    error = InvalidModelOutput(reason)
    evaluation_tasks._log_failure(run_id, step_id, "deep_match", error)
    event = json.loads(caplog.records[-1].getMessage())
    assert event == {
        "event": "evaluation_step_failed", "run_id": str(run_id),
        "step_id": str(step_id), "kind": "deep_match",
        "error_code": "evaluation_model_output_invalid", "reason": reason,
    }
    assert evaluation_tasks.error_code(error) == "evaluation_model_output_invalid"


def test_unknown_exception_text_and_codes_never_logged(caplog):
    secret = "private@example.com secret-key raw model response"
    for error in (RuntimeError(secret), InvalidModelOutput(secret)):
        evaluation_tasks._log_failure(uuid4(), uuid4(), "deep_match", error)
        event = json.loads(caplog.records[-1].getMessage())
        assert event["reason"] == "unclassified"
    assert secret not in caplog.text
