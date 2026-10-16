"""Execute the dashboard renderer against frozen identities, without live mail."""

import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess


def test_dashboard_shows_frozen_mailbox_and_template():
    scripts = Path(__file__).resolve().parents[2] / "skills/fmg-api/scripts"
    spec = importlib.util.spec_from_file_location(
        "mailbox_dashboard", scripts / "outreach_dashboard.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = {
        "data": {
            "id": "task-frozen",
            "name": "Frozen review",
            "revision": "rev",
            "state": "awaiting_approval",
            "mailbox_id": "studio-two",
            "sender": "frozen@example.com",
            "display_name": "Frozen Studio",
            "template": {"id": "game-outreach", "version": "5"},
            "template_version": "5",
            "smtp_password": "SECRET_PASSWORD",
            "stats": {"sent": 0, "replied": 1},
            "recipients": [],
        },
        "meta": {},
    }
    projected = module.delivery_view(payload)
    assert "SECRET_PASSWORD" not in json.dumps(projected)
    assert "replied" not in projected["data"]["stats"]
    page = (scripts / "outreach_dashboard.html").read_text()
    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    # Run the real render function. DOM stand-ins only collect visible text;
    # full browser layout and interaction QA is the controller's next gate.
    script = script[: script.index('$("search").oninput')]
    harness = r"""
const elements = new Map();
function element() { return {textContent: '', value: 'all', open:false, hidden:false, append(){}, replaceChildren(){}, contains(){return false}}; }
global.document = { getElementById(id) {if(!elements.has(id)) elements.set(id,element());return elements.get(id)},createElement:element,activeElement:null };
document.getElementById('search').value='';
"""
    result = subprocess.run(
        [
            shutil.which("node") or "node",
            "-e",
            harness
            + script
            + "\ndata="
            + json.dumps(projected["data"])
            + ";render();console.log(JSON.stringify(Object.fromEntries([...elements].map(([k,v])=>[k,v.textContent]))));",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    visible = json.loads(result.stdout)
    assert "studio-two" in visible["identity"]
    assert "Frozen Studio" in visible["identity"]
    assert "frozen@example.com" in visible["identity"]
    assert "game-outreach" in visible["template"] and "5" in visible["template"]
    assert "Reply" not in " ".join(visible.values())
