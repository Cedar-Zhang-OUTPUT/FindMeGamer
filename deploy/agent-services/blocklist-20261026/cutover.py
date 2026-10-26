"""Monitor-only cutover. Never restart send workers or release sender holds."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.update(
    FMG_AGENT_IMAGE="fmg-agent:sent-copy-20261020",
    FMG_AGENT_ENV_FILE="/etc/fmg-agent/multimail-20261017/service.env",
    FMG_AGENT_PG_ENV_FILE="/etc/fmg-agent/multimail-20261017/pg.env",
    FMG_AGENT_MAILBOXES_HOST_FILE="/etc/fmg-agent/multimail-20261017/mailboxes.json",
    FMG_AGENT_NETWORK="find-me-gamer-backend",
)


def run(*args):
    return subprocess.check_output(args, text=True)


def inspect(name):
    return json.loads(run("docker", "inspect", name))[0]


stage = Path(__file__).resolve().parent
monitor = inspect("fmg-agent-monitor-1")
labels = monitor["Config"]["Labels"]
assert monitor["Config"]["Image"] == "fmg-agent:text-pacing-20261022"
others = ["fmg-agent-" + x + "-1" for x in
          ("api", "dispatch", "mail-worker", "mail-worker-second", "worker")]
before = {x: inspect(x) for x in others}
files = labels["com.docker.compose.project.config_files"].split(",")
files += ["/opt/fmg-sent-read-20261023/compose.yaml"]
cmd = ["docker", "compose", "--project-name", "fmg-agent", "--project-directory",
       labels["com.docker.compose.project.working_dir"]]
for file in files:
    assert Path(file).is_file()
    cmd += ["-f", file]
old = json.loads(run(*cmd, "config", "--format", "json"))
new_cmd = cmd + ["-f", str(stage / "compose.yaml")]
new = json.loads(run(*new_cmd, "config", "--format", "json"))
expected = json.loads(json.dumps(old))
expected["services"]["monitor"]["image"] = "fmg-agent:blocklist-20261026"
assert new == expected, "Unexpected Compose changes"
# Config rendering must reproduce current monitor settings without exposing env.
for key, runtime_key in (("command", "Cmd"),):
    assert old["services"]["monitor"][key] == monitor["Config"][runtime_key]
runtime_env = dict(x.split("=", 1) for x in monitor["Config"]["Env"])
for key, value in old["services"]["monitor"]["environment"].items():
    assert runtime_env.get(key) == str(value), "Environment drift"
expected_mounts = {
    (v["target"], v["type"], v["source"] if v["type"] == "bind"
     else old["volumes"][v["source"]]["name"], not v.get("read_only", False))
    for v in old["services"]["monitor"]["volumes"]
}
assert expected_mounts == {
    (v["Destination"], v["Type"], v["Source"] if v["Type"] == "bind" else v["Name"], v["RW"])
    for v in monitor["Mounts"]
}, "Mount drift"
print("Compose preflight: only monitor image changes", flush=True)
if sys.argv[1:] != ["apply"]:
    raise SystemExit(0)

# SIGTERM drains the mailbox loops. Do not let Compose force-kill a live scan.
subprocess.check_call(["docker", "kill", "--signal=TERM", monitor["Id"]])
for _ in range(120):
    if not inspect("fmg-agent-monitor-1")["State"]["Running"]:
        break
    time.sleep(1)
else:
    raise SystemExit("Monitor has not drained; no force kill or replacement")
subprocess.check_call(new_cmd + ["up", "-d", "--no-deps", "monitor"])
after = inspect("fmg-agent-monitor-1")
assert after["Config"]["Image"] == "fmg-agent:blocklist-20261026"
for name, original in before.items():
    current = inspect(name)
    assert current["Id"] == original["Id"]
    assert current["State"]["StartedAt"] == original["State"]["StartedAt"]
    assert current["RestartCount"] == original["RestartCount"]
print("Only monitor replaced; all other application containers unchanged", flush=True)
