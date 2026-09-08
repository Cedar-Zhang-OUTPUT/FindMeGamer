"""Two bounded real B HTTP/worker SMTP protections, using synthetic capture only.

Run only during an exclusive owned-fixture window. Each scenario creates a new
Activity. No automatic retries or not-sent resolution are provided here. The
SMTP fault control is always restored to success after entering the context.
"""

from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
import json
import os
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request
from uuid import uuid4

if __package__:
    from .outreach_smoke import API, BACKEND, FIXED_HASH, IDENTITY, SMTP, UUID, SmokeError, compose_and_confirm, event_counts, fixed_hash, poll, prepare_members, require, validate_config, wait_captures
else:
    from outreach_smoke import API, BACKEND, FIXED_HASH, IDENTITY, SMTP, UUID, SmokeError, compose_and_confirm, event_counts, fixed_hash, poll, prepare_members, require, validate_config, wait_captures

SOURCE_NOTE = "Synthetic test operator verified this exact delivery's private local EML capture; capture confirms fixture submission, not external mailbox delivery."


class FailureAPI(API):
    """Add only explicit retry and verified-sent resolution to the success API."""

    def request(self, method, path, body=None, *, key=None, expected=(200, 201, 202)):
        match = re.fullmatch(rf"/api/v2/outreach/deliveries/{UUID}/(retry|resolve)", path)
        if not match:
            return super().request(method, path, body, key=key, expected=expected)
        action = match[1]
        require(method == "POST" and isinstance(body, dict), "recovery_request_not_allowed")
        keys = {"expected_attempt"} if action == "retry" else {"expected_attempt", "outcome", "source_note"}
        require(set(body) == keys and type(body.get("expected_attempt")) is int and body["expected_attempt"] >= 0, "recovery_payload_not_allowed")
        if action == "resolve":
            require(body["outcome"] == "sent" and isinstance(body["source_note"], str) and 0 < len(body["source_note"].strip()) <= 2000, "recovery_payload_not_allowed")
        request = Request(self.origin + path, data=json.dumps(body).encode(), headers={
            "Authorization": "Bearer " + self.key, "Content-Type": "application/json",
            "Idempotency-Key": key or str(uuid4()),
        }, method=method)
        try:
            try:
                response = self.opener.open(request, timeout=20)
            except HTTPError as error:
                response = error
            with response:
                require(response.code in expected, f"http_status_{response.code}")
                raw = response.read(2_000_001)
                require(len(raw) <= 2_000_000, "http_response_too_large")
                return json.loads(raw)
        except SmokeError:
            raise
        except (URLError, OSError, ValueError):
            raise SmokeError("http_request_failed") from None


class SMTPControl:
    def __init__(self, state, settle_seconds):
        self.state, self.settle_seconds = Path(state), settle_seconds
        require(not self.state.is_symlink() and self.state.stat().st_mode & 0o777 == 0o700, "state_not_private")
        path = self.state / "smtp-control.json"
        if path.exists() or path.is_symlink():
            require(not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600, "smtp_control_not_private")
            require(json.loads(path.read_text()) == {"mode": "success"}, "smtp_control_already_active")

    def set(self, mode):
        require(mode in {"success", "reject", "unknown_after_capture"}, "smtp_mode_not_allowed")
        path = self.state / "smtp-control.json"
        temporary = self.state / f"smtp-control-{uuid4()}.tmp"
        with os.fdopen(os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump({"mode": mode}, stream)
        temporary.replace(path)
        # Host read-back alone is not proof of Docker bind-mount visibility.
        # Give the rename time to propagate, then require actual transport events
        # after submission. A missing fault is a fixture failure, not a B defect.
        time.sleep(self.settle_seconds)
        require(json.loads(path.read_text()) == {"mode": mode}, "smtp_control_write_failed")


@contextmanager
def smtp_control(state, *, settle_seconds=0.35):
    control = SMTPControl(state, settle_seconds)
    try:
        yield control
    finally:
        control.set("success")


def smtp_events(state):
    path = state / "smtp-events.jsonl"
    if not path.exists():
        return []
    records = [json.loads(line) for line in path.read_text().splitlines()]
    require(all(set(item) == {"endpoint", "status"} and item["endpoint"] == "smtp" and item["status"] in {"captured", "rejected", "fail_before", "unknown_after_capture"} for item in records), "smtp_events_not_fixed_labels")
    return [item["status"] for item in records]


def verify_events(state, offset, expected):
    observed = smtp_events(state)[offset:]
    require(observed == expected, "smtp_fault_not_observed")
    return observed


def assert_single_capture(paths, snapshot):
    require(len(paths) == 1, "capture_not_one")
    message = BytesParser(policy=policy.default).parsebytes(paths[0].read_bytes())
    require(parseaddr(str(message["To"]))[1] == snapshot["recipient_email"] and parseaddr(str(message["From"])) == ("Toki", SMTP["username"]) and parseaddr(str(message["Reply-To"]))[1] == SMTP["reply_to"], "capture_identity_changed")
    require(str(message["Subject"]) == snapshot["subject"], "capture_subject_changed")
    body = message.get_body(preferencelist=("html",)).get_content().rstrip("\r\n")
    plain = message.get_body(preferencelist=("plain",)).get_content().rstrip("\r\n")
    require(body == snapshot["html"] and plain == snapshot["text"], "capture_frozen_body_changed")
    fragments = re.split(r'<span background-color="rgba\(255,246,122,0.8\)">.*?</span>', body, flags=re.S)
    require(len(fragments) == 5 and fixed_hash(snapshot["subject"], fragments) == FIXED_HASH, "capture_canonical_changed")


def new_scenario(api, nonce, record, checkpoint):
    """HTTP setup only: real discovery, preparation, DraftAI and human facts."""
    game = api.request("POST", "/api/v2/library/games", {
        "name": "LIMINAL: Within", "description": "Synthetic failure acceptance: interactive film and pixel RPG investigation.",
        "languages": ["English"], "tags": ["Adventure"],
        "reference_works": [{"name": "Synthetic comparison", "url": "https://example.com/synthetic-reference", "reason": "Synthetic recorded context"}],
    })
    activity = api.request("POST", "/api/v2/activities", {"game_id": game["id"], "name": "Synthetic SMTP protection " + nonce, "reference_work_ids": [item["id"] for item in game["reference_works"]]})
    record.update(game_id=game["id"], activity_id=activity["id"])
    checkpoint("discovery")
    created = api.request("POST", f"/api/v2/activities/{activity['id']}/discovery-plans", {
        "mode": "discover", "platforms": ["youtube"], "keywords": ["cozy cooperative"], "batch_target": 10, "result_limit": 30,
        "batch_request_budget": 20, "batch_scan_budget": 500, "total_request_budget": 60, "total_scan_budget": 2000,
        "filters": {"include_unknown_country": True, "include_unknown_language": True, "include_unknown_followers": True},
    })
    plan = poll(lambda: api.request("GET", f"/api/v2/discovery/plans/{created['plan_id']}"), lambda value: value["status"] in {"ready", "failed"})
    require(plan["status"] == "ready" and plan["query_id"], "planning_failed")
    query_path = f"/api/v2/discovery/queries/{plan['query_id']}"
    query = poll(lambda: api.request("GET", query_path), lambda value: value["status"] not in {"queued", "running"})
    require(query["status"] == "completed" and query["result_count"] == 3, "discovery_not_three")
    candidates = sorted(api.request("GET", query_path + "/results")["items"], key=lambda item: item["account_id"])
    require([(item["platform"], item["account_id"]) for item in candidates] == [("youtube", name) for name in ("UCmatchA001", "UCmatchB002", "UCmatchC003")], "discovery_not_synthetic")
    selections = prepare_members(api, activity["id"], candidates, nonce)
    batch = api.request("POST", f"/api/v2/activities/{activity['id']}/recipient-batches", {
        "request_id": str(uuid4()), "recipients": [{"selection_id": item["id"], "expected_revision": item["revision"], "context_token": item["context_token"]} for item in selections],
    })
    template = api.request("POST", "/api/v2/outreach/template-versions/canonical", {"game_id": game["id"]})
    require(template["fixed_hash"] == FIXED_HASH, "canonical_template_mismatch")
    checkpoint("drafting_and_facts")
    composition = compose_and_confirm(api, activity["id"], batch, template)
    path = f"/api/v2/outreach/compositions/{composition['id']}"
    excluded = [{"draft_id": item["id"], "reason": "Explicitly outside this one-recipient synthetic SMTP scenario"} for item in composition["drafts"][1:]]
    qualification = api.request("POST", path + "/qualification", {"excluded": excluded})
    require((qualification["total_count"], qualification["eligible_count"], qualification["excluded_count"]) == (3, 1, 2) and qualification["send_ready"] and qualification["sender"] == IDENTITY, "qualification_not_one_explicit_recipient")
    body = {"request_id": str(uuid4()), "qualification_token": qualification["qualification_token"], "excluded": excluded}
    record.update(composition_id=composition["id"], recipient_batch_id=batch["id"], request_id=body["request_id"])
    return path, body


def terminal_delivery(api, batch_id):
    batch = poll(lambda: api.request("GET", f"/api/v2/outreach/send-batches/{batch_id}"), lambda value: all(item["state"] not in {"queued", "sending"} for item in value["deliveries"]))
    require(len(batch["deliveries"]) == 1, "send_batch_not_one_recipient")
    return batch["deliveries"][0]


def run(client_private_dir):
    if __package__:
        from .manage import load_owned, private_write
    else:
        from manage import load_owned, private_write
    directory = Path(client_private_dir).absolute()
    try:
        config = load_owned(directory)
        validate_config(config)
    except (ValueError, OSError):
        raise SmokeError("not_owned_fixed_b_fixture") from None
    state = directory / "state"
    path = state / "control.json"
    require(not path.exists() or json.loads(path.read_text()) == {"source_fail": "none", "model_fail": "none", "hold": "none"}, "model_controls_not_success")
    nonce = uuid4().hex[:12]
    report_path = directory / f"outreach-failures-{nonce}.json"
    report = {"backend_revision": BACKEND, "migration": config["migration"], "run_id": nonce, "status": "running", "stage": "preflight", "scenarios": {}}
    api, before_models = FailureAPI(config), event_counts(state)

    def checkpoint(stage):
        report["stage"] = stage
        private_write(report_path, json.dumps(report, indent=2) + "\n", replace=True)

    checkpoint("preflight")
    try:
        with smtp_control(state) as control:
            api.request("PUT", "/api/v1/outreach/smtp", SMTP)
            for scenario in ("reject", "unknown_after_capture"):
                record = report["scenarios"][scenario] = {"status": "running"}
                phase = lambda stage: checkpoint(scenario + ":" + stage)
                phase("setup")
                composition_path, send_body = new_scenario(api, nonce + "-" + scenario, record, phase)
                captures_before = {item.name for item in state.glob("smtp-*.eml")}
                events_before = len(smtp_events(state))
                control.set(scenario)
                phase("fault_submission_requested")
                sent = api.request("POST", composition_path + "/send-batches", send_body)
                record["send_batch_id"] = sent["id"]
                phase("waiting_worker_outcome")
                delivery = terminal_delivery(api, sent["id"])
                record.update(delivery_id=delivery["id"], initial_state=delivery["state"], initial_attempt=delivery["attempt"], initial_capture_count=len([item for item in state.glob("smtp-*.eml") if item.name not in captures_before]), initial_smtp_events=smtp_events(state)[events_before:])
                phase("verify_actual_fault_injection")
                expected_events = ["rejected"] if scenario == "reject" else ["captured", "unknown_after_capture"]
                verify_events(state, events_before, expected_events)
                expected_state = "failed" if scenario == "reject" else "unknown"
                require(delivery["state"] == expected_state and delivery["attempt"] == 1 and delivery["retryable"] is (scenario == "reject"), "worker_fault_classification_mismatch")
                frozen = delivery["snapshot"]
                delivery_path = f"/api/v2/outreach/deliveries/{delivery['id']}"
                initial_count = 0 if scenario == "reject" else 1
                wait_captures(state, captures_before, initial_count, settle_seconds=2)
                control.set("success")
                if scenario == "reject":
                    phase("explicit_retry_same_delivery")
                    retried = api.request("POST", delivery_path + "/retry", {"expected_attempt": delivery["attempt"]})
                    require(retried["id"] == delivery["id"] and retried["snapshot"] == frozen, "retry_changed_frozen_delivery")
                    completed = terminal_delivery(api, sent["id"])
                    require(completed["state"] == "sent" and completed["attempt"] == 2 and completed["snapshot"] == frozen, "explicit_retry_not_sent_once")
                    paths = wait_captures(state, captures_before, 1, settle_seconds=2)
                    assert_single_capture(paths, frozen)
                    verify_events(state, events_before, ["rejected", "captured"])
                    record.update(status="passed", final_state="sent", final_attempt=2, captured_count=1, smtp_events=["rejected", "captured"])
                else:
                    phase("unknown_retry_blocked")
                    paths = wait_captures(state, captures_before, 1, settle_seconds=3)
                    assert_single_capture(paths, frozen)
                    unchanged = terminal_delivery(api, sent["id"])
                    require(unchanged["state"] == "unknown" and unchanged["attempt"] == 1, "unknown_automatically_retried")
                    api.request("POST", delivery_path + "/retry", {"expected_attempt": 1}, expected=(409,))
                    wait_captures(state, captures_before, 1)
                    verify_events(state, events_before, expected_events)
                    phase("explicit_verified_sent_resolution")
                    resolved = api.request("POST", delivery_path + "/resolve", {"expected_attempt": 1, "outcome": "sent", "source_note": SOURCE_NOTE})
                    require(resolved["state"] == "sent" and resolved["attempt"] == 1 and resolved["snapshot"] == frozen and resolved["resolution"]["source_note"] == SOURCE_NOTE and not resolved["retryable"], "verified_sent_resolution_changed_delivery")
                    blocked = api.request("POST", composition_path + "/qualification", {"excluded": send_body["excluded"]})
                    require(blocked["eligible_count"] == 0 and "already_invited" in blocked["members"][0]["missing_fields"] and blocked["members"][0]["blocking_delivery_id"] == delivery["id"], "resolved_invitation_not_blocked")
                    api.request("POST", composition_path + "/send-batches", {"request_id": str(uuid4()), "qualification_token": blocked["qualification_token"], "excluded": send_body["excluded"]}, expected=(409,))
                    wait_captures(state, captures_before, 1, settle_seconds=2)
                    verify_events(state, events_before, expected_events)
                    require(api.request("GET", f"/api/v2/activities/{record['activity_id']}/send-batches")["total"] == 1, "ordinary_duplicate_batch_created")
                    record.update(status="passed", final_state="sent", final_attempt=1, captured_count=1, smtp_events=expected_events, retry_status=409, ordinary_invitation_status=409)
                phase("complete")
        require(json.loads((state / "smtp-control.json").read_text()) == {"mode": "success"}, "smtp_restore_not_success")
        delta = event_counts(state) - before_models
        require(delta["planning"] == 2 and delta["drafting"] == 4, "real_model_http_not_observed")
        report.update(status="passed", smtp_control_restored="success", http_counts=dict(delta), report_path=str(report_path))
        checkpoint("complete")
        return report
    except Exception as error:
        report.update(status="failed", error=str(error) if isinstance(error, SmokeError) else "unexpected_failure_smoke_error")
        try:
            report["smtp_control_restored"] = "success" if json.loads((state / "smtp-control.json").read_text()) == {"mode": "success"} else "not_success"
        except (OSError, ValueError):
            report["smtp_control_restored"] = "unconfirmed"
        checkpoint(report["stage"])
        raise SmokeError(report["error"]) from None
