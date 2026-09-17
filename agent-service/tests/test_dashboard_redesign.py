import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import urllib.request
import urllib.error
import pytest

from test_email_templates import variables
from test_email_sending import sending, headers


def test_v2_outreach_buttons_are_inside_document(sending):
    app, client, owner, _, _ = sending
    app.state.settings.outreach_public_url = "https://service.example.com"
    response = client.post("/v1/outreach/tasks", headers=headers(owner, "designed"), json={
        "name": "Design", "template_id": "game-outreach", "template_version": "2",
        "recipients": [{"creator_id": "alice", "to": "alice@example.com", "variables": variables()}],
    })
    assert response.status_code == 201
    task = response.json()["data"]
    assert task["state"] == "awaiting_approval"
    html = task["recipients"][0]["message"]["html"]
    assert html.index("choice=yes") < html.index("</body>")
    assert html.index("choice=no") < html.index("</body>")
    assert "<!--FMG_RESPONSE_ACTIONS-->" not in html


def test_template_v2_preserves_v1_and_escapes_content():
    from fmg_agent.email.templates import get_template, render_template
    v1 = get_template("game-outreach", "1")
    v2 = get_template("game-outreach")
    assert v1["version"] == "1" and v2["version"] == "2"
    values = variables()
    values["personalization"] = '<script>alert("x")</script>'
    result = render_template(v2, values)
    assert '<script>' not in result["html"]
    assert '&lt;script&gt;' in result["html"]
    assert 'role="presentation"' in result["html"]
    assert '<!--FMG_RESPONSE_ACTIONS-->' in result["html"]
    assert result["text"] == render_template(v1, values)["text"]


def test_research_snapshot_preserves_briefs_and_reports_invalid(tmp_path):
    scripts = Path(__file__).resolve().parents[2] / "skills/fmg-research/scripts"
    sys.path.insert(0, str(scripts))
    try:
        spec = importlib.util.spec_from_file_location("research_dashboard", scripts / "research_dashboard.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    directory = tmp_path / "runs/test/matches"
    directory.mkdir(parents=True)
    brief = {"creator": {"display_name": "Example"}, "match": {"decision": "suitable"}}
    (directory / "good.json").write_text(json.dumps(brief))
    (directory / "partial.json").write_text('{')
    outside = tmp_path / "private.json"
    outside.write_text(json.dumps(brief))
    (directory / "link.json").symlink_to(outside)
    result = module.snapshot(tmp_path, "test")
    assert result["matches"] == [brief]
    assert result["unreadable"] == 2
    assert (directory / "partial.json").read_text() == '{'


def test_research_dashboard_serves_live_local_files_read_only(tmp_path):
    script = Path(__file__).resolve().parents[2] / "skills/fmg-research/scripts/research_dashboard.py"
    directory = tmp_path / "runs/test/matches"
    directory.mkdir(parents=True)
    process = subprocess.Popen([sys.executable, str(script), "--root", str(tmp_path), "--run-id", "test"], stdout=subprocess.PIPE, text=True)
    try:
        url = json.loads(process.stdout.readline())["url"]
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            assert response.status == 200
            assert "default-src 'none'" in response.headers["Content-Security-Policy"]
        with opener.open(url + "data", timeout=5) as response:
            assert json.load(response)["matches"] == []
        brief = {"creator": {"display_name": "New result"}, "match": {"decision": "suitable"}}
        (directory / "new.json").write_text(json.dumps(brief))
        with opener.open(url + "data", timeout=5) as response:
            assert json.load(response)["matches"] == [brief]
        with pytest.raises(urllib.error.HTTPError) as error:
            opener.open(urllib.request.Request(url, method="POST"), timeout=5)
        assert error.value.code == 501
        with pytest.raises(urllib.error.HTTPError) as error:
            opener.open(urllib.request.Request(url, headers={"Host": "foreign.example"}), timeout=5)
        assert error.value.code == 403
    finally:
        process.terminate()
        process.wait(timeout=5)
