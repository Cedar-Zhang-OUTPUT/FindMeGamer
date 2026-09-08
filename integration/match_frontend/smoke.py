"""Bounded real HTTP acceptance checks against the owned running fixture."""

from collections import Counter
import json
import time

from fixture import DEFAULT_CONTROL, write_control
from manage import command, load_owned, private_write, request


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def poll(config, path, ready, *, seconds=45):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = request(config, "GET", path)
        if ready(value):
            return value
        time.sleep(0.15)
    raise AssertionError("Fixture operation did not reach its expected terminal state")


def settled_query(config, query_id):
    return poll(
        config,
        f"/api/v2/discovery/queries/{query_id}",
        lambda value: value["status"] not in {"queued", "running"},
    )


def new_plan(config, activity, *, target=2, platforms=None):
    return request(
        config,
        "POST",
        f"/api/v2/activities/{activity}/discovery-plans",
        {
            "mode": "discover",
            "platforms": platforms or ["youtube", "x"],
            "keywords": ["cozy cooperative"],
            "batch_target": target,
            "result_limit": 30,
            "batch_request_budget": 20,
            "batch_scan_budget": 500,
            "total_request_budget": 60,
            "total_scan_budget": 2000,
            "filters": {
                "include_unknown_country": True,
                "include_unknown_language": True,
                "include_unknown_followers": True,
            },
        },
    )


def ready_plan(config, plan_id):
    return poll(
        config,
        f"/api/v2/discovery/plans/{plan_id}",
        lambda value: value["status"] in {"ready", "failed"},
    )


def event_counts(directory):
    path = directory / "state/events.jsonl"
    records = (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )
    return Counter(item["endpoint"] for item in records if item["status"] == 200)


def run(directory):
    config = load_owned(directory)
    state_dir = directory / "state"
    write_control(state_dir, DEFAULT_CONTROL)
    before = event_counts(directory)
    report = {"backend_revision": config["backend_revision"], "checks": []}
    activity = request(
        config,
        "POST",
        "/api/v2/activities",
        {
            "game_id": config["game_id"],
            "name": "Match fixture acceptance",
            "reference_work_ids": config["reference_work_ids"],
        },
    )
    require(
        bool(activity["source_snapshot"]["game"]["description"]),
        "Game description was not snapshotted",
    )
    require(
        len(activity["source_snapshot"]["references"]) == 1,
        "Reference was not snapshotted",
    )
    created = new_plan(config, activity["id"])
    plan = ready_plan(config, created["plan_id"])
    require(
        plan["status"] == "ready" and plan["query_id"],
        "Actual Flash planning did not succeed",
    )
    query_id = plan["query_id"]
    query = settled_query(config, query_id)
    require(
        query["status"] == "paused" and query["result_count"] == 2,
        "First page did not publish two deduplicated creators",
    )
    first = request(config, "GET", f"/api/v2/discovery/queries/{query_id}/results")
    first_ids = {item["creator_id"] for item in first["items"]}
    stopped = request(config, "POST", f"/api/v2/discovery/queries/{query_id}/stop")
    require(stopped["status"] == "stopped", "Stop was not persisted")
    require(
        set(
            item["creator_id"]
            for item in request(
                config, "GET", f"/api/v2/discovery/queries/{query_id}/results"
            )["items"]
        )
        == first_ids,
        "Stop lost prior results",
    )
    for _ in range(4):
        request(config, "POST", f"/api/v2/discovery/queries/{query_id}/continue", {})
        query = settled_query(config, query_id)
        if query["status"] == "completed":
            break
        require(query["status"] == "paused", "Discovery entered an unexpected state")
    require(
        query["status"] == "completed" and query["result_count"] == 6,
        "Two-page sources did not exhaust with six unique accounts",
    )
    require(
        {value["status"] for value in query["sources"].values()} == {"exhausted"},
        "Sources did not truthfully report exhaustion",
    )
    results = request(config, "GET", f"/api/v2/discovery/queries/{query_id}/results")
    require(
        len({(item["platform"], item["account_id"]) for item in results["items"]}) == 6,
        "Duplicate accounts leaked",
    )
    require(
        first_ids.issubset({item["creator_id"] for item in results["items"]}),
        "Continue replaced prior results",
    )
    require(
        all(item["selected"] is False for item in results["items"]),
        "Discovery auto-selected a creator",
    )
    works = 0
    for item in results["items"]:
        profile = request(
            config, "GET", f"/api/v2/library/creators/{item['creator_id']}"
        )
        require(profile["id"] == item["creator_id"], "Library identity differs")
        works += profile["work_count"]
    require(works == 8, "Duplicate content was not deduplicated in shared Library")
    report["checks"].append("plan_discover_two_pages_dedupe_library_stop_continue")
    evaluation = request(
        config, "POST", f"/api/v2/discovery/queries/{query_id}/evaluations", {}
    )
    evaluation_path = f"/api/v2/discovery/evaluations/{evaluation['evaluation_id']}"
    evaluated = poll(
        config,
        evaluation_path,
        lambda value: value["status"] not in {"queued", "running"},
    )
    require(
        evaluated["status"] == "completed" and evaluated["matched_count"] == 6,
        "Actual Flash/Pro evaluation failed",
    )
    ranked = request(config, "GET", evaluation_path + "/results")
    require(len(ranked["items"]) == 6, "Evaluation results are missing")
    for item in ranked["items"]:
        require(
            item["match_brief"]["confidence"] == "limited",
            "Fixture metadata overstated its evidence",
        )
        require(
            item["selected"] is False and item["sender_watched"] is False,
            "Evaluation implied selection or viewing",
        )
        require(
            not ({"score", "rank", "numeric_rank"} & set(item)),
            "Numeric ranking leaked into public results",
        )
        require(item["fit_group"] == "potential_fit", "Typed fit classification failed")
    delta = event_counts(directory) - before
    require(
        dict(delta)
        == {
            "planning": 1,
            "youtube": 2,
            "youtube_channels": 2,
            "x": 2,
            "screening": 1,
            "deep": 6,
            "ranking": 1,
        },
        "Real gateway HTTP counts differ from bounded scenario",
    )
    report.update(
        {
            "success_activity_id": activity["id"],
            "success_query_id": query_id,
            "success_evaluation_id": evaluation["evaluation_id"],
            "creators": 6,
            "persisted_works": works,
            "success_http_counts": dict(delta),
        }
    )
    report["checks"].append(
        "flash_screen_pro_deep_rank_typed_briefs_no_selection_or_score"
    )
    private_write(
        directory / "success-report.json",
        json.dumps(report, indent=2) + "\n",
        replace=True,
    )
    return report
