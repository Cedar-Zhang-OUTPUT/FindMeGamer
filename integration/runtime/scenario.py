from __future__ import annotations

import json
from email import policy
from email.parser import BytesParser
from html import unescape
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urlsplit


ROOT = Path(__file__).resolve().parents[2]
PROJECT = os.environ["FMG_INTEGRATION_PROJECT"]
ENV_FILE = os.environ["FMG_COMPOSE_ENV_FILE"]
BASE_URL = f"http://127.0.0.1:{os.environ['FMG_INTEGRATION_HTTP_PORT']}"
WORKSPACE_KEY = "integration-workspace-key"
COMPOSE = [
    "docker",
    "compose",
    "--project-name",
    PROJECT,
    "--env-file",
    ENV_FILE,
    "-f",
    str(ROOT / "compose.yaml"),
    "-f",
    str(ROOT / "integration/compose.integration.yaml"),
]
DOCKER_COMMAND_TIMEOUT = 5.0


def compose(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*COMPOSE, *arguments],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
        timeout=DOCKER_COMMAND_TIMEOUT,
    )


def wait_for(label: str, predicate, timeout: float = 120.0, interval: float = 0.5):
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except (
            AssertionError,
            HTTPError,
            OSError,
            subprocess.SubprocessError,
            ValueError,
        ) as error:
            last = error
        time.sleep(interval)
    raise AssertionError(f"timed out waiting for {label}; last={last!r}")


def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {WORKSPACE_KEY}"}
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        headers["Content-Type"] = "application/json"
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    request = Request(BASE_URL + path, data=body, method=method, headers=headers)
    with urlopen(request, timeout=10) as response:
        if response.status >= 300:
            raise AssertionError(f"{method} {path} returned {response.status}")
        return json.loads(response.read())


def sql(statement: str) -> str:
    completed = compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-XAt",
        "-U",
        "integration",
        "-d",
        "find_me_gamer_integration",
        "-c",
        statement,
    )
    return completed.stdout.strip()


def state_file_exists(pattern: str) -> bool:
    completed = compose(
        "exec",
        "-T",
        "api",
        "sh",
        "-c",
        f"find /integration-state -maxdepth 1 -name '{pattern}' -print -quit",
        check=False,
    )
    return completed.returncode == 0 and bool(completed.stdout.strip())


def wait_job(job_id: str, expected: str = "succeeded") -> dict[str, Any] | bool:
    payload = request_json("GET", f"/api/v1/jobs/{job_id}")
    if payload["status"] == "failed":
        raise AssertionError(f"analysis job failed safely: {payload.get('error')}")
    return payload if payload["status"] == expected else False


def wait_match(match_id: str, expected: str = "succeeded") -> dict[str, Any] | bool:
    payload = request_json("GET", f"/api/v1/matches/{match_id}")
    if payload["status"] == "failed":
        raise AssertionError(f"match failed safely: {payload.get('error')}")
    return payload if payload["status"] == expected else False


def force_restart_worker() -> None:
    compose("stop", "--timeout", "1", "worker")
    time.sleep(6)
    compose("start", "worker")


def assert_project_service_health() -> None:
    expected = {"proxy", "api", "worker", "beat", "postgres", "redis"}
    configured = set(compose("config", "--services").stdout.split())
    assert configured == expected, configured
    for service in sorted(expected):
        container_id = compose("ps", "-q", service).stdout.strip()
        assert container_id, f"{service} has no integration container"
        inspected = (
            subprocess.run(
                [
                    "docker",
                    "inspect",
                    "--format",
                    '{{ index .Config.Labels "com.docker.compose.project" }} {{ .State.Status }} {{ if .State.Health }}{{ .State.Health.Status }}{{ end }}',
                    container_id,
                ],
                text=True,
                capture_output=True,
                check=True,
                timeout=DOCKER_COMMAND_TIMEOUT,
            )
            .stdout.strip()
            .split()
        )
        assert inspected[0] == PROJECT, (service, inspected)
        assert inspected[1] == "running", (service, inspected)
        assert inspected[2] == "healthy", (service, inspected)
    ready = request_json("GET", "/health/ready")
    assert ready.get("status") == "ok", ready


def configure_fake_secrets() -> None:
    for service in ("youtube", "deepseek"):
        response = request_json(
            "PUT",
            f"/api/v1/settings/connections/{service}",
            payload={"secret": f"synthetic-{service}-integration-key"},
        )
        assert response["configured"] is True


def create_analysis(kind: str, url: str, key: str) -> dict[str, Any]:
    response = request_json(
        "POST",
        "/api/v1/jobs/analysis",
        payload={"target_type": kind, "url": url},
        idempotency_key=key,
    )
    assert response["outcome"] == "job", response
    return response


def assert_no_numeric_match_keys(value: object) -> None:
    forbidden = {"rank", "score", "total_score", "dimension_scores", "backend_order"}
    if isinstance(value, dict):
        overlap = forbidden.intersection(value)
        assert (
            not overlap
        ), f"public Match leaked numeric ordering keys: {sorted(overlap)}"
        for nested in value.values():
            assert_no_numeric_match_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            assert_no_numeric_match_keys(nested)


def assert_library_profile(kind: str, profile_id: str, query: str) -> None:
    path = f"/api/v1/profiles/{kind}"
    detail = request_json("GET", f"{path}/{profile_id}")
    assert detail["id"] == profile_id
    assert detail["source_status"]["visual_analysis"] == "available", detail[
        "source_status"
    ]
    request_json("PATCH", f"{path}/{profile_id}/favorite", payload={"favorite": True})
    listed = request_json(
        "GET", path + "?" + urlencode({"only_collection": "true", "query": query})
    )
    assert profile_id in {item["id"] for item in listed["items"]}
    request_json("PATCH", f"{path}/{profile_id}/favorite", payload={"favorite": False})
    collected = request_json("GET", path + "?only_collection=true")
    assert profile_id not in {item["id"] for item in collected["items"]}


def outreach_scenario(match_id: str, creator_ids: list[str]) -> None:
    smtp = request_json(
        "PUT",
        "/api/v1/outreach/smtp",
        payload={
            "host": "smtp.integration.invalid",
            "port": 465,
            "encryption": "tls",
            "username": "sender@example.com",
            "password": "synthetic-smtp-integration-key",
            "from_name": "Integration Team",
            "reply_to": "reply@example.com",
            "emails_per_minute": 60,
        },
    )
    assert smtp["configured"] and "password" not in smtp
    template = request_json(
        "POST",
        "/api/v1/outreach/templates",
        payload={
            "name": "Integration invitation",
            "subject_template": "{{creator_name}} and {{game_name}}",
            "body_markdown": "Hello {{creator_name}}. {{match_reason}} {{steam_url}} From {{sender_name}}.",
            "accepted_label": "Yes, count me in",
            "declined_label": "No, thank you",
        },
    )
    expected_recipients = {}
    for index, creator_id in enumerate(creator_ids):
        email = f"creator{index}@example.com"
        profile = request_json(
            "PATCH",
            f"/api/v1/profiles/creators/{creator_id}/manual",
            payload={"contact_email": email, "notes": "Integration contact."},
        )
        assert email in {contact["email"] for contact in profile["contacts"]}
        expected_recipients[email] = "accepted" if index == 0 else "declined"
    payload = {
        "match_task_id": match_id,
        "creator_ids": creator_ids,
        "template_id": template["id"],
        "recipient_selections": [
            {"creator_id": creator_id, "email": f"creator{index}@example.com"}
            for index, creator_id in enumerate(creator_ids)
        ],
    }
    preview = request_json(
        "POST", "/api/v1/outreach/send-batches/preview", payload=payload
    )
    assert {item["recipient_email"] for item in preview["items"]} == set(
        expected_recipients
    )
    assert not state_file_exists("smtp-*.eml"), "preview sent email"
    batch = request_json(
        "POST",
        "/api/v1/outreach/send-batches",
        payload=payload,
        idempotency_key="integration-outreach-send",
    )
    repeated = request_json(
        "POST",
        "/api/v1/outreach/send-batches",
        payload=payload,
        idempotency_key="integration-outreach-send",
    )
    assert repeated["id"] == batch["id"]
    campaign_path = f"/api/v1/outreach/campaigns/{batch['campaign_id']}"

    def sent_campaign():
        campaign = request_json("GET", campaign_path)
        return campaign if campaign["state"] == "completed" else False

    campaign = wait_for(
        "queued Outreach deliveries sent by Worker", sent_campaign, timeout=60
    )
    assert campaign["metrics"] == {
        "sent_creators": 2,
        "accepted": 0,
        "declined": 0,
        "no_response": 2,
        "failed": 0,
        "response_rate": 0.0,
    }
    captured = json.loads(
        compose(
            "exec",
            "-T",
            "api",
            "python",
            "-c",
            "import json,pathlib; print(json.dumps([p.read_text() for p in sorted(pathlib.Path('/integration-state').glob('smtp-*.eml'))]))",
        ).stdout
    )
    assert len(captured) == 2, "idempotent send created duplicate emails"
    for raw_message in captured:
        message = BytesParser(policy=policy.default).parsebytes(raw_message.encode())
        recipient = str(message["To"])
        choice = expected_recipients[recipient]
        html = message.get_body(preferencelist=("html",)).get_content()
        links = re.findall(r'href="([^\"]+/r/[^\"]+)"', html)
        urls = {urlsplit(unescape(link)).query: unescape(link) for link in links}
        assert set(urls) == {"choice=accepted", "choice=declined"}
        target = urls[f"choice={choice}"]
        assert target.startswith(BASE_URL + "/r/")
        with urlopen(target, timeout=10) as response:
            confirmation = response.read().decode()
        assert "Confirm response" in confirmation
        assert "Yes, count me in" in confirmation and "No, thank you" in confirmation
        # Link-preview GETs must not record a response; only an explicit POST does.
        before = request_json("GET", campaign_path)
        matching = [
            d
            for b in before["send_batches"]
            for d in b["deliveries"]
            if d["recipient_email"] == recipient
        ]
        assert matching[0]["response_state"] == "no_response"
        for posted_choice in (
            choice,
            choice,
            "declined" if choice == "accepted" else "accepted",
        ):
            request = Request(
                BASE_URL + urlsplit(target).path,
                data=urlencode({"choice": posted_choice}).encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                assert (
                    f"Your final response is {choice.title()}."
                    in response.read().decode()
                )
    final = request_json("GET", campaign_path)
    assert final["metrics"] == {
        "sent_creators": 2,
        "accepted": 1,
        "declined": 1,
        "no_response": 0,
        "failed": 0,
        "response_rate": 1.0,
    }
    assert len(final["send_batches"]) == 1
    assert_no_numeric_match_keys(request_json("GET", f"/api/v1/matches/{match_id}"))
    assert "synthetic-smtp-integration-key" not in json.dumps(final)
    print(
        "PASS: Library → Match → Outreach preview/send → Yes/No and duplicate prevention"
    )


def recovery_scenario() -> None:
    wait_for("six healthy integration services", health_probe, timeout=150)
    configure_fake_secrets()

    creator_one = create_analysis(
        "creator",
        "https://www.youtube.com/channel/UCrecovery01",
        "integration-analyze-recovery",
    )
    wait_for(
        "controlled Analyze fake call", lambda: state_file_exists("analysis-blocked")
    )
    force_restart_worker()
    creator_one_done = wait_for(
        "redelivered Analyze Job", lambda: wait_job(creator_one["id"]), timeout=150
    )
    creator_one_id = creator_one_done["profile_id"]
    assert (
        sql(
            "SELECT count(*) FROM creator_profiles WHERE youtube_channel_id='UCrecovery01'"
        )
        == "1"
    )

    creator_two = create_analysis(
        "creator",
        "https://www.youtube.com/channel/UCcreator002",
        "integration-analyze-second",
    )
    creator_two_done = wait_for(
        "second Creator Analyze", lambda: wait_job(creator_two["id"]), timeout=120
    )
    creator_two_id = creator_two_done["profile_id"]

    game = create_analysis(
        "game", "https://store.steampowered.com/app/1245620", "integration-analyze-game"
    )
    game_done = wait_for("Game Analyze", lambda: wait_job(game["id"]), timeout=120)
    game_id = game_done["profile_id"]
    assert_library_profile("games", game_id, "Strategy")
    assert_library_profile("creators", creator_one_id, "Creator")

    match = request_json(
        "POST",
        "/api/v1/matches",
        payload={"game_id": game_id},
        idempotency_key="integration-match-recovery",
    )
    match_id = match["id"]
    wait_for(
        "durable first pairwise checkpoint and controlled second call",
        lambda: (
            int(
                sql(
                    f"SELECT count(*) FROM match_pairwise_records WHERE match_task_id='{match_id}' AND state='succeeded'"
                )
            )
            >= 1
            and state_file_exists("match-blocked-*")
        ),
        timeout=120,
    )
    partial = request_json("GET", f"/api/v1/matches/{match_id}")
    assert partial["status"] == "running", partial
    assert partial["result_state"] == "pending", partial
    assert partial["recommended_matches"] == [] and partial["other_matches"] == []

    first_checkpoint_id = sql(
        f"SELECT creator_id FROM match_pairwise_records WHERE match_task_id='{match_id}' AND state='succeeded' ORDER BY creator_id LIMIT 1"
    )
    force_restart_worker()
    match_done = wait_for(
        "redelivered Match", lambda: wait_match(match_id), timeout=150
    )
    results = match_done["recommended_matches"] + match_done["other_matches"]
    assert {item["creator"]["id"] for item in results} == {
        creator_one_id,
        creator_two_id,
    }
    assert len(results) == 2
    assert (
        sql(f"SELECT count(*) FROM match_result_items WHERE match_task_id='{match_id}'")
        == "2"
    )
    assert_no_numeric_match_keys(match_done)

    completed_ids = compose(
        "exec", "-T", "api", "cat", "/integration-state/pairwise-completed"
    ).stdout.splitlines()
    assert completed_ids.count(first_checkpoint_id) == 1, completed_ids
    checkpoint_calls = compose(
        "exec", "-T", "api", "cat", "/integration-state/calls.log"
    ).stdout.splitlines()
    assert checkpoint_calls.count(f"pairwise-call {first_checkpoint_id}") == 1
    outreach_scenario(match_id, [creator_one_id, creator_two_id])

    sql(
        f"UPDATE creator_profiles SET next_analysis_at=now()-interval '1 day' WHERE id='{creator_one_id}'"
    )
    beat_job = wait_for(
        "Beat-created due re-analysis Job",
        lambda: sql(
            f"SELECT id FROM analysis_jobs WHERE canonical_target_id='UCrecovery01' AND mode='reanalyze' ORDER BY created_at DESC LIMIT 1"
        ),
        timeout=30,
    )
    wait_for(
        "Beat re-analysis completion", lambda: wait_job(str(beat_job)), timeout=120
    )
    assert (
        sql(
            "SELECT count(*) FROM analysis_jobs "
            "WHERE canonical_target_id='UCrecovery01' AND mode='reanalyze'"
        )
        == "1"
    )

    stable_before = {
        "creator_one": request_json(
            "GET", f"/api/v1/profiles/creators/{creator_one_id}"
        ),
        "creator_two": request_json(
            "GET", f"/api/v1/profiles/creators/{creator_two_id}"
        ),
        "game": request_json("GET", f"/api/v1/profiles/games/{game_id}"),
        "analysis": request_json("GET", f"/api/v1/jobs/{creator_one['id']}"),
        "match": request_json("GET", f"/api/v1/matches/{match_id}"),
    }
    compose("stop", "worker", "beat")
    compose("exec", "-T", "redis", "redis-cli", "FLUSHALL")
    compose("start", "worker", "beat")
    wait_for("worker and Beat after Redis clear", healthy_worker_and_beat, timeout=120)
    stable_after = {
        "creator_one": request_json(
            "GET", f"/api/v1/profiles/creators/{creator_one_id}"
        ),
        "creator_two": request_json(
            "GET", f"/api/v1/profiles/creators/{creator_two_id}"
        ),
        "game": request_json("GET", f"/api/v1/profiles/games/{game_id}"),
        "analysis": request_json("GET", f"/api/v1/jobs/{creator_one['id']}"),
        "match": request_json("GET", f"/api/v1/matches/{match_id}"),
    }
    assert stable_after == stable_before

    call_log = compose(
        "exec", "-T", "api", "cat", "/integration-state/calls.log"
    ).stdout
    for expected in (
        "youtube channels",
        "steam appdetails",
        "deepseek CreatorVideoBatchDigest",
        "deepseek CreatorContentFormatReduction",
        "deepseek CreatorPresentationReduction",
        "deepseek CreatorPerformanceAudienceReduction",
        "deepseek CreatorCommercialSafetyReduction",
        "deepseek CreatorBriefSynthesis",
        "vision inline_images verified CreatorVisualAnalysis",
        "vision inline_images verified GameVisualAnalysis",
        "deepseek ScreeningOutput",
        "deepseek PairwiseMatchBrief",
        "deepseek FinalRankingOutput",
        "s3 put_object",
        "smtp send_message",
    ):
        assert expected in call_log, expected
    for forbidden in (
        WORKSPACE_KEY,
        "master.key",
        "Authorization",
        "synthetic-integration-secret",
    ):
        assert forbidden not in call_log
    assert_project_service_health()


def healthy_worker_and_beat() -> bool:
    for service in ("worker", "beat"):
        container_id = compose("ps", "-q", service).stdout.strip()
        if not container_id:
            return False
        state = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{if .State.Health}}{{.State.Health.Status}}{{end}}",
                container_id,
            ],
            text=True,
            capture_output=True,
            check=True,
            timeout=DOCKER_COMMAND_TIMEOUT,
        ).stdout.strip()
        if state != "healthy":
            return False
    return True


def health_probe() -> bool:
    assert_project_service_health()
    return True


def main() -> None:
    scenario = sys.argv[1]
    if scenario == "health":
        wait_for("six healthy integration services", health_probe, timeout=150)
    elif scenario == "recovery":
        recovery_scenario()
    else:
        raise SystemExit(f"unknown scenario: {scenario}")
    print(f"PASS: {scenario}")


if __name__ == "__main__":
    main()
