"""Bounded failure/held-page acceptance; reset only this fixture's file controls."""

import json
import time

from fixture import DEFAULT_CONTROL, write_control
from manage import load_owned, private_write, request
from smoke import new_plan, poll, ready_plan, require, settled_query


def run(directory):
    config = load_owned(directory)
    state = directory / "state"
    report = {"checks": []}
    activity = request(
        config,
        "POST",
        "/api/v2/activities",
        {
            "game_id": config["game_id"],
            "name": "Match fixture bounded failure controls",
            "reference_work_ids": config["reference_work_ids"],
        },
    )
    try:
        write_control(state, DEFAULT_CONTROL | {"model_fail": "planning"})
        created = new_plan(config, activity["id"], target=30)
        failed = ready_plan(config, created["plan_id"])
        require(
            failed["status"] == "failed"
            and failed["retryable"]
            and failed["query_id"] is None,
            "Planning HTTP failure was not surfaced truthfully",
        )
        report["planning_failure_code"] = failed["error_code"]
        write_control(state, DEFAULT_CONTROL | {"source_fail": "x"})
        request(config, "POST", f"/api/v2/discovery/plans/{created['plan_id']}/retry")
        plan = ready_plan(config, created["plan_id"])
        require(
            plan["status"] == "ready" and plan["attempt"] == 2,
            "Explicit plan retry did not recover",
        )
        query_id = plan["query_id"]
        partial = settled_query(config, query_id)
        require(
            partial["status"] == "paused" and partial["result_count"] == 3,
            "Partial source failure lost successful YouTube results",
        )
        require(
            partial["sources"]["youtube"]["status"] == "exhausted"
            and partial["sources"]["x"]["status"] == "failed",
            "Source failure state is inaccurate",
        )
        report["partial_source_status"] = partial["status"]
        report["partial_source_reason"] = partial["batches"][-1]["reason"]
        preserved = {
            item["creator_id"]
            for item in request(
                config, "GET", f"/api/v2/discovery/queries/{query_id}/results"
            )["items"]
        }
        write_control(state, DEFAULT_CONTROL)
        request(config, "POST", f"/api/v2/discovery/queries/{query_id}/continue", {})
        recovered = settled_query(config, query_id)
        require(
            recovered["status"] == "completed" and recovered["result_count"] == 6,
            "Continue did not recover failed source",
        )
        require(
            preserved.issubset(
                {
                    item["creator_id"]
                    for item in request(
                        config, "GET", f"/api/v2/discovery/queries/{query_id}/results"
                    )["items"]
                }
            ),
            "Source recovery replaced Library identities",
        )
        report["checks"].extend(
            [
                "planning_failure_explicit_retry",
                "source_partial_failure_preserves_results_continue_recovers",
            ]
        )

        write_control(state, DEFAULT_CONTROL | {"model_fail": "deep"})
        evaluation = request(
            config, "POST", f"/api/v2/discovery/queries/{query_id}/evaluations", {}
        )
        evaluation_path = f"/api/v2/discovery/evaluations/{evaluation['evaluation_id']}"
        failed_eval = poll(
            config,
            evaluation_path,
            lambda value: value["status"] not in {"queued", "running"},
        )
        require(
            failed_eval["status"] == "failed"
            and failed_eval["retryable"]
            and failed_eval["usage"]["failed_steps"] == 6,
            "Deep model failure was masked",
        )
        write_control(state, DEFAULT_CONTROL)
        request(config, "POST", evaluation_path + "/retry", {})
        recovered_eval = poll(
            config,
            evaluation_path,
            lambda value: value["status"] not in {"queued", "running"},
        )
        require(
            recovered_eval["status"] == "completed"
            and recovered_eval["matched_count"] == 6,
            "Explicit evaluation step retry failed",
        )
        report["checks"].append("pro_deep_failure_explicit_step_retry")

        created = new_plan(config, activity["id"])
        plan = ready_plan(config, created["plan_id"])
        query_id = plan["query_id"]
        first = settled_query(config, query_id)
        require(
            first["result_count"] == 2 and first["status"] == "paused",
            "Held scenario first page failed",
        )
        before = len((state / "events.jsonl").read_text().splitlines())
        write_control(state, DEFAULT_CONTROL | {"hold": "youtube"})
        request(config, "POST", f"/api/v2/discovery/queries/{query_id}/continue", {})
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            records = [
                json.loads(line)
                for line in (state / "events.jsonl").read_text().splitlines()[before:]
            ]
            if any(
                item == {"endpoint": "youtube", "status": "held"} for item in records
            ):
                break
            time.sleep(0.1)
        else:
            raise AssertionError("Actual YouTube HTTP page was not held")
        request(config, "POST", f"/api/v2/discovery/queries/{query_id}/stop")
        write_control(state, DEFAULT_CONTROL)
        stopped = poll(
            config,
            f"/api/v2/discovery/queries/{query_id}",
            lambda value: value["status"] == "stopped"
            and value["batches"][-1]["status"] == "stopped",
        )
        require(
            stopped["result_count"] == 3,
            "In-flight page did not finish atomically on stop",
        )
        require(
            stopped["sources"]["youtube"]["status"] == "exhausted"
            and "x" not in stopped["sources"],
            "Stop scheduled an extra source page",
        )
        request(config, "POST", f"/api/v2/discovery/queries/{query_id}/continue", {})
        resumed = settled_query(config, query_id)
        if resumed["status"] == "paused":
            request(
                config, "POST", f"/api/v2/discovery/queries/{query_id}/continue", {}
            )
            resumed = settled_query(config, query_id)
        require(
            resumed["status"] == "completed" and resumed["result_count"] == 6,
            "Held-stop continuation lost results",
        )
        report["checks"].append(
            "held_actual_http_page_stop_atomic_preservation_continue"
        )
        private_write(
            directory / "failure-report.json",
            json.dumps(report, indent=2) + "\n",
            replace=True,
        )
        return report
    finally:
        write_control(state, DEFAULT_CONTROL)
