"""Owned fixture: brief, defaults and game-bound preview; never submits email."""
import json
from pathlib import Path
import sys
from uuid import uuid4

from manage import load_owned, private_write, request, command
from smoke import new_plan, ready_plan, settled_query, poll, require, event_counts
from outreach_smoke import prepare_members

PIN = "6d8425a99d7bd050424904a1492166b14f2ee5ac"
SMTP = {"host": "smtp.integration.invalid", "port": 465, "encryption": "tls", "username": "synthetic-sender@example.com", "password": "synthetic-fixture-only", "from_name": "Synthetic Demo Sender", "reply_to": "synthetic-sender@example.com", "emails_per_minute": 60}


def sender_mode(directory, missing):
    config = load_owned(directory)
    require(config["backend_revision"] == PIN, "Wrong fixture pin")
    if not missing:
        request(config, "PUT", "/api/v1/outreach/smtp", SMTP)
        return {"sender_mode": "synthetic_configured"}
    # Test-only configuration fault: the normal UI correctly disallows saving
    # an empty From Name. Retain the encrypted synthetic secret, remove only its
    # public SMTP metadata, and restore through the real configuration API.
    code = """from runtime import configure
configure()
from app.core.database import session_scope
from app.db.models.settings import SharedSettings
from sqlalchemy import select
with session_scope() as session:
    row = session.scalar(select(SharedSettings).with_for_update())
    state = dict(row.service_connection_state or {})
    assert state.get('smtp', {}).get('username') in (None, 'synthetic-sender@example.com')
    state.pop('smtp', None)
    row.service_connection_state = state
    session.commit()
"""
    command(directory, "exec", "-T", "api", "python", "-c", code)
    return {"sender_mode": "missing"}


def run(directory):
    config = load_owned(directory)
    require(config["backend_revision"] == PIN, "Wrong fixture pin")
    report_path = directory / "meeting-report.json"
    require(not report_path.exists(), "This smoke is fresh-instance only; inspect its checkpoint")
    report = {"backend_revision": PIN, "checks": []}
    private_write(report_path, json.dumps(report))
    before = event_counts(directory)

    class API:
        def request(self, method, path, body=None):
            require(not path.endswith("/send-batches"), "No email submission in this smoke")
            return request(config, method, path, body)

    api = API()
    def save(**values):
        report.update(values)
        private_write(report_path, json.dumps(report, indent=2) + "\n", replace=True)

    activity = api.request("POST", "/api/v2/activities", {"game_id": config["game_id"], "name": "Synthetic meeting acceptance", "campaign_brief": "Focus on cooperative garden creators.", "reference_work_ids": config["reference_work_ids"]})
    save(activity_id=activity["id"])
    planned = new_plan(config, activity["id"], target=2, platforms=["youtube"])
    plan = ready_plan(config, planned["plan_id"])
    require(plan["status"] == "ready", "Planning failed")
    query = settled_query(config, plan["query_id"])
    selections_path = f"/api/v2/activities/{activity['id']}/selections"
    selected = api.request("GET", selections_path)["items"]
    require(len(selected) == query["result_count"] == 2, "First batch defaults missing")
    current = api.request("GET", f"/api/v2/activities/{activity['id']}")
    require(current["initial_selection_initialized"], "Marker missing")
    cancelled = selected[0]
    api.request("POST", selections_path + f"/{cancelled['id']}/cancel", {"expected_revision": cancelled["revision"]})
    api.request("PATCH", f"/api/v2/activities/{activity['id']}/campaign-brief", {"expected_revision": current["revision"], "campaign_brief": "Focus on gentle exploration creators."})
    require(api.request("GET", f"/api/v2/discovery/plans/{plan['id']}")["source_snapshot"]["campaign_brief"] == activity["campaign_brief"], "Old plan brief rewritten")
    api.request("POST", f"/api/v2/discovery/queries/{query['id']}/continue", {})
    appended = settled_query(config, query["id"])
    require(appended["result_count"] == 3, "Append did not add candidate")
    require(api.request("GET", selections_path)["total"] == 1, "Append/reset changed selections")
    require(not api.request("GET", selections_path + f"/{cancelled['id']}")["active"], "Cancellation lost")
    save(query_id=query["id"], plan_id=plan["id"], cancelled_selection_id=cancelled["id"])
    rows = api.request("GET", f"/api/v2/discovery/queries/{query['id']}/results")["items"]
    chosen = next(row for row in rows if row["id"] == selected[1]["candidate_id"])
    prepared = prepare_members(api, activity["id"], [chosen], "meeting")
    member = prepared[0]
    batch = api.request("POST", f"/api/v2/activities/{activity['id']}/recipient-batches", {"request_id": str(uuid4()), "recipients": [{"selection_id": member["id"], "expected_revision": member["revision"], "context_token": member["context_token"]}]})
    save(recipient_batch_id=batch["id"])

    def compose(template):
        item = api.request("POST", f"/api/v2/activities/{activity['id']}/compositions", {"request_id": str(uuid4()), "recipient_batch_id": batch["id"], "template_version_id": template["id"]})
        return poll(config, f"/api/v2/outreach/compositions/{item['id']}", lambda value: all(d["status"] not in {"pending", "running"} for d in value["drafts"]))

    missing_template = api.request("POST", "/api/v2/outreach/template-versions/canonical", {"game_id": config["game_id"]})
    missing = compose(missing_template)
    qualification = api.request("POST", f"/api/v2/outreach/compositions/{missing['id']}/qualification", {"excluded": []})
    require(not qualification["send_ready"] and "sender_identity_missing" in qualification["members"][0]["missing_fields"], "Missing sender not blocked")
    save(missing_sender_composition_id=missing["id"], missing_sender_template_id=missing_template["id"])
    api.request("PUT", "/api/v1/outreach/smtp", SMTP)
    template = api.request("POST", "/api/v2/outreach/template-versions/canonical", {"game_id": config["game_id"]})
    require(template["id"] != missing_template["id"] and template["source_metadata"]["kind"] == "game_bound", "Template did not follow sender/game facts")
    composition = compose(template)
    draft = composition["drafts"][0]
    require(draft["status"] == "succeeded" and draft["rendered"], "Real synthetic drafting failed")
    path = f"/api/v2/outreach/compositions/{composition['id']}"
    api.request("POST", path + "/sender-facts", {"members": [{"draft_id": draft["id"], "expected_revision": draft["revision"], "context_token": draft["context_token"]}], "following": True, "enjoyed": True, "liked": True})
    qualification = api.request("POST", path + "/qualification", {"excluded": []})
    require(qualification["send_ready"], "Synthetic sender repair not send-ready")
    require("Moonseed Garden Together" in draft["rendered"]["text"] and "LIMINAL" not in draft["rendered"]["text"], "Wrong game rendered")
    require(not list((directory / "state").glob("smtp-*.eml")), "Unexpected SMTP submission")
    save(composition_id=composition["id"], template_id=template["id"], fixed_hash=template["fixed_hash"], selected_creator_id=chosen["creator_id"], selected_selection_id=member["id"], checks=["brief_frozen_in_old_plan", "first_batch_default_once", "cancel_append_preserved", "explicit_recipient_subset", "missing_sender_blocks_send", "synthetic_sender_new_template_repairs", "game_bound_real_draft_preview", "zero_smtp"], synthetic_http_calls=dict(event_counts(directory) - before))
    return report


if __name__ == "__main__":
    directory = Path(sys.argv[1]).absolute()
    if sys.argv[2:] == ["sender-missing"]:
        result = sender_mode(directory, True)
    elif sys.argv[2:] == ["sender-configured"]:
        result = sender_mode(directory, False)
    elif len(sys.argv) == 2:
        result = run(directory)
    else:
        raise SystemExit("Unknown fixture operation")
    print(json.dumps(result, indent=2))
