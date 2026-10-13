"""The browser projection hides replies without dropping delivery protections."""

import json
from html.parser import HTMLParser
from pathlib import Path
import subprocess
import sys

import httpx
import pytest


class TableHeadings(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.headings = []

    def handle_starttag(self, tag, attrs):
        self.in_heading = tag == "th"

    def handle_endtag(self, tag):
        if tag == "th":
            self.in_heading = False

    def handle_data(self, value):
        if self.in_heading:
            self.headings.append(value.strip())


@pytest.mark.parametrize("malformed", [None, "recipient", "stats"])
def test_dashboard_projects_delivery_only_and_preserves_drafts_and_safety(
    tmp_path, malformed
):
    payload = {
        "data": {
            "id": "task",
            "name": "Delivery review",
            "state": "blocked",
            "revision": "frozen-revision",
            "stats": {
                "sent": 1,
                "failed": 0,
                "unknown": 1,
                "bounced": 1,
                "retry_queued": 1,
                "retry_unknown": 1,
                "replied": 1,
                "automatic": 1,
                "reply_rate": 0.5,
            },
            "monitoring": {"state": "active", "last_success": "2026-10-13T05:00:00Z"},
            "sender_safety": {"state": "paused", "reason": "provider_rate_limited"},
            "recipients": [
                {
                    "id": "one",
                    "creator_id": "Creator",
                    "state": "unknown",
                    "code": "graph_confirmation_lost",
                    "reply_state": "bounced",
                    "message": {
                        "from": "publisher@example.com",
                        "to": "creator@example.com",
                        "subject": "Saved subject",
                        "text": "Frozen draft",
                    },
                    "bounce_retry": {"state": "unknown", "send_id": "retry-one"},
                    "replies": [
                        {
                            "kind": "human",
                            "body": "PRIVATE_REPLY_MUST_NOT_REACH_BROWSER",
                        }
                    ],
                }
            ],
        },
        "meta": {"request_id": "read-request"},
    }
    if malformed == "recipient":
        payload["data"]["recipients"] = [None]
    elif malformed == "stats":
        payload["data"]["stats"] = []
    source = tmp_path / "task.json"
    source.write_text(json.dumps(payload))
    calls = tmp_path / "calls.jsonl"
    executable = tmp_path / "fmg-fixture"
    executable.write_text(
        f"#!{sys.executable}\nimport json,sys\nfrom pathlib import Path\n"
        f"with open({str(calls)!r},'a') as f: f.write(json.dumps(sys.argv[1:])+'\\n')\n"
        f"print(Path({str(source)!r}).read_text())\n"
    )
    executable.chmod(0o700)
    script = (
        Path(__file__).resolve().parents[2]
        / "skills/fmg-api/scripts/outreach_dashboard.py"
    )
    process = subprocess.Popen(
        [sys.executable, str(script), "--task-id", "task", "--fmg", str(executable)],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        url = json.loads(process.stdout.readline())["url"]
        with httpx.Client(trust_env=False) as client:
            response = client.get(url + "data")
            if malformed:
                assert response.status_code == 503
                assert response.json()["error"].startswith("Refresh failed")
                return
            assert response.status_code == 200
            data = response.json()["data"]
            assert "PRIVATE_REPLY_MUST_NOT_REACH_BROWSER" not in response.text
            assert not {"replied", "automatic", "reply_rate"} & data["stats"].keys()
            recipient = data["recipients"][0]
            assert not {"reply_state", "replies"} & recipient.keys()
            assert recipient["delivery_bounced"] is True
            assert recipient["message"] == payload["data"]["recipients"][0]["message"]
            assert (
                recipient["state"] == "unknown"
                and recipient["code"] == "graph_confirmation_lost"
            )
            assert recipient["bounce_retry"]["send_id"] == "retry-one"
            assert data["sender_safety"] == payload["data"]["sender_safety"]
            assert data["monitoring"] == payload["data"]["monitoring"]
            assert (
                data["revision"] == "frozen-revision" and data["stats"]["bounced"] == 1
            )
            assert client.post(url + "data").status_code == 501
            assert (
                client.get(url, headers={"Host": "foreign.example"}).status_code == 403
            )
            assert json.loads(source.read_text()) == payload
        assert [json.loads(line) for line in calls.read_text().splitlines()] == [
            ["outreach", "task", "get", "task"]
        ]
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_dashboard_has_delivery_columns_only():
    page = (
        Path(__file__).resolve().parents[2]
        / "skills/fmg-api/scripts/outreach_dashboard.html"
    )
    parser = TableHeadings()
    parser.feed(page.read_text())
    assert parser.headings == ["Creator / recipient", "Sending", "Draft"]
