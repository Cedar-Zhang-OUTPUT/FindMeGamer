"""Synthetic, real HTTP/Celery Outreach A+B success acceptance, never live SMTP.

Import and call run(private_directory) only with the owner's exclusive fixture
window. This deliberately does not change controls, retry failed sends, resolve
unknown delivery, or invoke business classes directly. Failures leave a private
checkpoint; inspect its safe identifiers before deciding whether to run again.
"""

from collections import Counter
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from hashlib import sha256
import html
import json
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

BACKEND = "ece2e9d9558dfe057dc40ad58bd98a86e3149dd5"
FIXED_HASH = "0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93"
RAW_HASH = "6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd"
SLOTS = ("firstName", "channelName", "reference", "observation")
OBSERVATION = "contrasted the quiet station with the sudden reveal"
SMTP = {
    "host": "smtp.integration.invalid", "port": 465, "encryption": "tls",
    "username": "sender@example.com", "password": "synthetic-smtp-integration-key",
    "from_name": "Toki", "reply_to": "sender@example.com", "emails_per_minute": 60,
}
IDENTITY = {"address": "sender@example.com", "name": "Toki", "reply_to": "sender@example.com"}
UUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
ROUTES = {
    "GET": [
        rf"/api/v2/library/creators/{UUID}", rf"/api/v2/activities/{UUID}",
        rf"/api/v2/discovery/plans/{UUID}", rf"/api/v2/discovery/queries/{UUID}(?:/results)?",
        rf"/api/v2/activities/{UUID}/selections/{UUID}",
        rf"/api/v2/activities/{UUID}/recipient-batches/{UUID}",
        rf"/api/v2/outreach/template-versions\?game_id={UUID}",
        rf"/api/v2/outreach/compositions/{UUID}", rf"/api/v2/outreach/send-batches/{UUID}",
        rf"/api/v2/activities/{UUID}/send-batches",
    ],
    "POST": [
        r"/api/v2/library/games", r"/api/v2/activities",
        rf"/api/v2/library/creators/{UUID}/(?:contacts|works)",
        rf"/api/v2/activities/{UUID}/(?:discovery-plans|selections|recipient-batches|compositions)",
        rf"/api/v2/activities/{UUID}/selections/{UUID}/update",
        r"/api/v2/outreach/template-versions/canonical",
        rf"/api/v2/outreach/compositions/{UUID}/(?:sender-facts|qualification|send-batches)",
    ],
    "PATCH": [rf"/api/v2/library/creators/{UUID}"],
    "PUT": [r"/api/v1/outreach/smtp"],
}


class SmokeError(RuntimeError):
    """Only fixed, non-sensitive labels may cross the reporting boundary."""


def require(condition, label):
    if not condition:
        raise SmokeError(label)


def validate_config(config):
    try:
        origin = urlsplit(config["base_url"])
        valid = (
            config["backend_revision"] == BACKEND and config["migration"] == "20260908_0017"
            and isinstance(config["workspace_key"], str) and bool(config["workspace_key"].strip())
            and origin.scheme == "http" and origin.hostname == "127.0.0.1"
            and origin.port is not None and 1024 <= origin.port <= 65535
            and origin.port not in {18090, 53251, 59414, 65164}
            and origin.netloc == f"127.0.0.1:{origin.port}"
            and not (origin.path or origin.query or origin.fragment)
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    require(valid, "not_fixed_b_loopback_fixture")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class API:
    def __init__(self, config):
        validate_config(config)
        self.origin, self.key = config["base_url"], config["workspace_key"]
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, method, path, body=None, *, key=None, expected=(200, 201, 202)):
        require(any(re.fullmatch(pattern, path) for pattern in ROUTES.get(method, [])), "request_not_allowed")
        if method == "PUT":
            require(body == SMTP, "smtp_not_synthetic")
        headers = {"Authorization": "Bearer " + self.key, "Content-Type": "application/json"}
        if method == "POST":
            headers["Idempotency-Key"] = key or str(uuid4())
        request = Request(self.origin + path, data=None if body is None else json.dumps(body).encode(), headers=headers, method=method)
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


def poll(read, ready, *, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read()
        if ready(value):
            return value
        time.sleep(0.05)
    raise SmokeError("operation_timeout")


def wait_captures(state, before, count, *, seconds=45, settle_seconds=1):
    deadline, settled = time.monotonic() + seconds, None
    while time.monotonic() < deadline:
        paths = sorted(path for path in state.glob("smtp-*.eml") if path.name not in before)
        require(len(paths) <= count, "capture_count_exceeded")
        complete = len(paths) == count
        for path in paths:
            require(not path.is_symlink() and path.stat().st_mode & 0o777 == 0o600, "capture_not_private")
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            complete = complete and bool(message.get_body(preferencelist=("plain",))) and bool(message.get_body(preferencelist=("html",))) and not message.defects
        if complete:
            settled = settled or time.monotonic()
            if time.monotonic() - settled >= settle_seconds:
                return paths
        else:
            settled = None
        time.sleep(0.02)
    raise SmokeError("capture_timeout")


def event_counts(state):
    path = state / "events.jsonl"
    return Counter(item["endpoint"] for item in (json.loads(line) for line in path.read_text().splitlines()) if item["status"] == 200) if path.exists() else Counter()


def fixed_hash(subject, fragments):
    return sha256((subject + "\n" + "<slot/>".join(fragments)).encode()).hexdigest()


def assert_captures(paths, deliveries):
    by_email = {item["snapshot"]["recipient_email"]: item["snapshot"] for item in deliveries}
    require(len(by_email) == len(paths) == 2, "capture_recipient_count")
    seen = set()
    for path in paths:
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        recipient = parseaddr(str(message["To"]))[1]
        require(recipient in by_email and recipient not in seen, "capture_recipient_mismatch")
        seen.add(recipient)
        snapshot = by_email[recipient]
        require(parseaddr(str(message["From"])) == ("Toki", SMTP["username"]), "capture_sender_mismatch")
        require(parseaddr(str(message["Reply-To"]))[1] == SMTP["reply_to"], "capture_reply_mismatch")
        require(str(message["Subject"]) == snapshot["subject"], "capture_subject_mismatch")
        body = message.get_body(preferencelist=("html",)).get_content().rstrip("\r\n")
        plain = message.get_body(preferencelist=("plain",)).get_content().rstrip("\r\n")
        require(body == snapshot["html"] and plain == snapshot["text"], "capture_body_snapshot_mismatch")
        slots = re.findall(r'<span background-color="rgba\(255,246,122,0.8\)">(.*?)</span>', body, flags=re.S)
        require(slots == [html.escape(snapshot["values"][key]) for key in SLOTS], "capture_four_slots_mismatch")
        fragments = re.split(r'<span background-color="rgba\(255,246,122,0.8\)">.*?</span>', body, flags=re.S)
        require(len(fragments) == 5 and fixed_hash(snapshot["subject"], fragments) == FIXED_HASH, "capture_fixed_template_changed")
        require(body.count("<p>") == 20 and not any(value in body for value in ("Choice=", "Yes, I'm in", "/r/", "<img")), "capture_cta_or_tracking")


def prepare_members(api, activity_id, candidates, nonce):
    selections = []
    for index, candidate in enumerate(candidates):
        creator_path = f"/api/v2/library/creators/{candidate['creator_id']}"
        creator = api.request("GET", creator_path)
        creator = api.request("PATCH", creator_path, {"expected_revision": creator["revision"], "public_name": f"Synthetic Creator {index + 1}"})
        contact_id = None
        if index < 2:
            address = f"outreach-{nonce}-{index + 1}@example.com"
            creator = api.request("POST", creator_path + "/contacts", {
                "expected_revision": creator["revision"], "email": address,
                "purpose": "Synthetic acceptance only", "source_url": "https://example.com/synthetic-contact",
            })
            contact_id = next(item["id"] for item in creator["contacts"] if item["email"] == address)
        work_body = {
            "expected_identity_revision": creator["source_identity"]["revision"],
            "content_title": f"Synthetic recorded scene {index + 1} [Excerpt]",
            "source_url": f"https://example.com/outreach/{nonce}/{index + 1}", "content_type": "commentary",
        }
        if index < 2:
            work_body.update(evidence_excerpt=OBSERVATION, verification_notes="Synthetic fixture recorded observation; not a real creator viewing claim.", timestamp_seconds=42)
        work = api.request("POST", creator_path + "/works", work_body)
        selected = api.request("POST", f"/api/v2/activities/{activity_id}/selections", {"candidate_id": candidate["id"]})
        selection_path = f"/api/v2/activities/{activity_id}/selections/{selected['id']}"
        selected = api.request("GET", selection_path)
        selected = api.request("POST", selection_path + "/update", {
            "expected_revision": selected["revision"], "context_token": selected["context_token"],
            "contact_id": contact_id, "work_ids": [work["id"]], "confirm_public_name": True,
        })
        selections.append(selected)
    return selections


def compose_and_confirm(api, activity_id, batch, template):
    composition = api.request("POST", f"/api/v2/activities/{activity_id}/compositions", {
        "request_id": str(uuid4()), "recipient_batch_id": batch["id"], "template_version_id": template["id"],
    })
    path = f"/api/v2/outreach/compositions/{composition['id']}"
    composition = poll(lambda: api.request("GET", path), lambda item: all(draft["status"] not in {"pending", "running"} for draft in item["drafts"]))
    require(composition["recipient_count"] == 3 and [draft["status"] for draft in composition["drafts"]] == ["succeeded", "succeeded", "needs_repair"], "real_draft_task_failed")
    for draft in composition["drafts"][:2]:
        require(draft["values"] == {
            "firstName": draft["input"]["public_name"], "channelName": draft["input"]["channel_name"],
            "reference": draft["input"]["reference"], "observation": OBSERVATION + ".",
        } and set(draft["slot_sources"]) == set(SLOTS), "draft_not_bound_to_recorded_sources")
        require(not draft["sender_facts_valid"], "sender_facts_inferred")
    # Explicit test-operator attestation about synthetic facts only. A real user
    # must independently make these choices; discovery/model output is not proof.
    api.request("POST", path + "/sender-facts", {
        "members": [{"draft_id": item["id"], "expected_revision": item["revision"], "context_token": item["context_token"]} for item in composition["drafts"][:2]],
        "following": True, "enjoyed": True, "liked": True,
    })
    confirmed = api.request("GET", path)
    require(all(item["sender_facts_valid"] for item in confirmed["drafts"][:2]), "explicit_facts_not_persisted")
    return confirmed


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
    require(not state.is_symlink() and state.stat().st_mode & 0o777 == 0o700, "state_not_private")
    for filename, default in (("control.json", {"source_fail": "none", "model_fail": "none", "hold": "none"}), ("smtp-control.json", {"mode": "success"})):
        path = state / filename
        require(not path.exists() or json.loads(path.read_text()) == default, "controls_not_success")
    nonce = uuid4().hex[:12]
    report_path = directory / f"outreach-success-{nonce}.json"
    report = {"backend_revision": BACKEND, "migration": config["migration"], "run_id": nonce, "status": "running", "checks": [], "stage": "setup"}

    def checkpoint(stage):
        report["stage"] = stage
        private_write(report_path, json.dumps(report, indent=2) + "\n", replace=True)

    api, before_events = API(config), event_counts(state)
    before_captures = {path.name for path in state.glob("smtp-*.eml")}
    checkpoint("create_game_activity")
    try:
        game = api.request("POST", "/api/v2/library/games", {
            "name": "LIMINAL: Within", "description": "Synthetic internal acceptance: interactive film and pixel RPG investigation.",
            "developer": "Ontology Play (synthetic fixture)", "languages": ["English"], "tags": ["Adventure"],
            "reference_works": [{"name": "Synthetic recorded comparison", "url": "https://example.com/synthetic-reference", "reason": "Synthetic evidence context"}],
        })
        activity = api.request("POST", "/api/v2/activities", {"game_id": game["id"], "name": "Synthetic Outreach " + nonce, "reference_work_ids": [item["id"] for item in game["reference_works"]]})
        report.update(game_id=game["id"], activity_id=activity["id"])
        checkpoint("real_discovery")
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
        require(all(not item["selected"] for item in candidates), "discovery_auto_selected")
        report["query_id"] = plan["query_id"]
        checkpoint("explicit_preparation")
        selections = prepare_members(api, activity["id"], candidates, nonce)
        batch = api.request("POST", f"/api/v2/activities/{activity['id']}/recipient-batches", {
            "request_id": str(uuid4()), "recipients": [{"selection_id": item["id"], "expected_revision": item["revision"], "context_token": item["context_token"]} for item in selections],
        })
        require(batch["recipient_count"] == 3 and batch["recipients"][2]["snapshot"]["selected_contact"] is None, "incomplete_recipient_dropped")
        report["recipient_batch_id"] = batch["id"]
        report["checks"].append("real_discovery_explicit_three_choices_incomplete_member_preserved")
        checkpoint("canonical_registration")
        listing = api.request("GET", f"/api/v2/outreach/template-versions?game_id={game['id']}")
        require(listing["items"] == [] and listing["builtin"]["requires_explicit_registration"], "implicit_template_registration")
        template = api.request("POST", "/api/v2/outreach/template-versions/canonical", {"game_id": game["id"]})
        source = template["source_metadata"]
        require(source["document_id"] == "Ieqid5pULoUSqMxOtKTc156xnLe" and source["revision"] == 69 and source["raw_hash"] == RAW_HASH and template["fixed_hash"] == FIXED_HASH and len(template["fixed_fragments"]) == 5 and fixed_hash(template["subject"], template["fixed_fragments"]) == FIXED_HASH, "canonical_source_mismatch")
        api.request("PUT", "/api/v1/outreach/smtp", SMTP)
        checkpoint("real_drafting_and_explicit_facts")
        composition = compose_and_confirm(api, activity["id"], batch, template)
        report["composition_id"] = composition["id"]
        path = f"/api/v2/outreach/compositions/{composition['id']}"
        qualification = api.request("POST", path + "/qualification", {"excluded": []})
        require(tuple(qualification[key] for key in ("total_count", "eligible_count", "repair_count", "excluded_count")) == (3, 2, 1, 0) and not qualification["send_ready"], "qualification_dropped_repairs")
        excluded = [{"draft_id": composition["drafts"][2]["id"], "reason": "Synthetic member lacks recorded evidence and selected email"}]
        qualification = api.request("POST", path + "/qualification", {"excluded": excluded})
        require(tuple(qualification[key] for key in ("total_count", "eligible_count", "repair_count", "excluded_count")) == (3, 2, 0, 1) and qualification["send_ready"] and qualification["sender"] == IDENTITY, "explicit_qualification_failed")
        report["checks"].append("canonical_four_slots_real_draft_ai_explicit_facts_full_n_qualification")
        send_body = {"request_id": str(uuid4()), "qualification_token": qualification["qualification_token"], "excluded": excluded}
        send_key = str(uuid4())
        report["send_request_id"] = send_body["request_id"]
        checkpoint("final_send_requested")
        sent = api.request("POST", path + "/send-batches", send_body, key=send_key)
        report["send_batch_id"] = sent["id"]
        checkpoint("waiting_actual_worker_capture")
        completed = poll(lambda: api.request("GET", f"/api/v2/outreach/send-batches/{sent['id']}"), lambda value: all(item["state"] not in {"queued", "sending"} for item in value["deliveries"]))
        deliveries = completed["deliveries"]
        require(len(deliveries) == 2 and all(item["state"] == "sent" and item["attempt"] == 1 for item in deliveries), "actual_send_not_two_sent")
        captures = wait_captures(state, before_captures, 2)
        assert_captures(captures, deliveries)
        report.update(delivery_ids=[item["id"] for item in deliveries], captured_count=len(captures))
        report["checks"].append("actual_worker_socket_free_capture_two_canonical_mime_messages")
        checkpoint("durable_replay")
        for key in (send_key, str(uuid4())):
            replay = api.request("POST", path + "/send-batches", send_body, key=key)
            require(replay["id"] == sent["id"] and [(item["id"], item["snapshot"]) for item in replay["deliveries"]] == [(item["id"], item["snapshot"]) for item in deliveries], "durable_replay_changed_snapshot")
        wait_captures(state, before_captures, 2)
        checkpoint("cross_composition_duplicate_block")
        another = compose_and_confirm(api, activity["id"], batch, template)
        another_path = f"/api/v2/outreach/compositions/{another['id']}"
        another_excluded = [{"draft_id": another["drafts"][2]["id"], "reason": excluded[0]["reason"]}]
        blocked = api.request("POST", another_path + "/qualification", {"excluded": another_excluded})
        require(blocked["eligible_count"] == 0 and not blocked["send_ready"] and all("already_invited" in item["missing_fields"] and item["blocking_delivery_id"] in report["delivery_ids"] for item in blocked["members"][:2]), "same_activity_duplicate_not_blocked")
        api.request("POST", another_path + "/send-batches", {"request_id": str(uuid4()), "qualification_token": blocked["qualification_token"], "excluded": another_excluded}, expected=(409,))
        require(api.request("GET", f"/api/v2/activities/{activity['id']}/send-batches")["total"] == 1, "duplicate_send_batch_created")
        wait_captures(state, before_captures, 2)
        original = api.request("GET", f"/api/v2/activities/{activity['id']}/recipient-batches/{batch['id']}")
        require([item["snapshot"] for item in original["recipients"]] == [item["snapshot"] for item in batch["recipients"]] and api.request("GET", f"/api/v2/activities/{activity['id']}")["source_snapshot"] == activity["source_snapshot"], "original_discovery_or_recipient_snapshot_changed")
        delta = event_counts(state) - before_events
        require(delta["drafting"] == 4 and delta["planning"] == 1, "real_model_http_not_observed")
        report.update(status="passed", selected_count=3, eligible_count=2, excluded_count=1, http_counts=dict(delta), report_path=str(report_path))
        report["checks"].append("durable_http_replay_cross_composition_guard_original_snapshots_preserved")
        checkpoint("complete")
        return report
    except Exception as error:
        report.update(status="failed", error=str(error) if isinstance(error, SmokeError) else "unexpected_smoke_error")
        checkpoint(report["stage"])
        raise SmokeError(report["error"]) from None
