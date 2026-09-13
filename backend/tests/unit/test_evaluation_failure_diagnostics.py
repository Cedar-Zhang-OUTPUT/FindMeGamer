import json
from uuid import uuid4

import pytest

from app.integrations.errors import InvalidModelOutput
from app.workers import evaluation_tasks


@pytest.mark.parametrize(
    "reason",
    [
        "evaluation_candidate_id_invalid",
        "evaluation_work_ids_invalid",
        "evaluation_evidence_invalid",
        "evaluation_narrative_invalid",
        "deepseek_model_output_invalid",
    ],
)
def test_safe_reason_logged_without_changing_public_error(reason, caplog):
    run_id, step_id = uuid4(), uuid4()
    error = InvalidModelOutput(reason)
    evaluation_tasks._log_failure(run_id, step_id, "deep_match", error)
    event = json.loads(caplog.records[-1].getMessage())
    assert event == {
        "event": "evaluation_step_failed",
        "run_id": str(run_id),
        "step_id": str(step_id),
        "kind": "deep_match",
        "error_code": "evaluation_model_output_invalid",
        "reason": reason,
    }
    assert evaluation_tasks.error_code(error) == "evaluation_model_output_invalid"


def test_unknown_exception_text_and_codes_never_logged(caplog):
    secret = "private@example.com secret-key raw model response"
    for error in (RuntimeError(secret), InvalidModelOutput(secret)):
        evaluation_tasks._log_failure(uuid4(), uuid4(), "deep_match", error)
        event = json.loads(caplog.records[-1].getMessage())
        assert event["reason"] == "unclassified"
    assert secret not in caplog.text


def test_parallel_deep_steps_bind_distinct_context_and_log_every_failure(caplog):
    import logging
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from app.core.analysis_diagnostics import model_call

    logging.getLogger("app.core.analysis_diagnostics").disabled = False
    caplog.set_level(logging.INFO, logger="app.core.analysis_diagnostics")
    run, search = uuid4(), uuid4()
    steps, candidates = [uuid4(), uuid4()], [uuid4(), uuid4()]

    def execute(kind, payload):
        with model_call(
            provider="deepseek",
            model="deepseek-flash",
            schema="EvaluationMatchBrief",
            attempt="initial",
            max_tokens=4096,
        ):
            pass
        raise InvalidModelOutput("evaluation_narrative_invalid")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                copy_context().run,
                evaluation_tasks._execute_diagnostic_claim,
                run,
                search,
                (
                    step,
                    uuid4(),
                    "deep_match",
                    {"candidate": {"candidate_id": str(candidate)}},
                ),
                execute,
            )
            for step, candidate in zip(steps, candidates)
        ]
        for future in futures:
            with pytest.raises(InvalidModelOutput):
                future.result()
    events = [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name == "app.core.analysis_diagnostics"
    ]
    failures = [e for e in events if e["event"] == "evaluation_step_finished"]
    assert len(failures) == 2 and all(e["status"] == "failed" for e in failures)
    assert {(e["step_id"], e["candidate_id"]) for e in failures} == set(
        zip(map(str, steps), map(str, candidates))
    )
    assert all(
        e["evaluation_run_id"] == str(run) and e["search_id"] == str(search)
        for e in failures
    )
    assert len({e["call_id"] for e in failures}) == 2
