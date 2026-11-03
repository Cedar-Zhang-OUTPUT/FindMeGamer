"""Pinned per-role reply rollout; no forced kills, no sender/task hold changes."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

STAGE = Path("/opt/fmg-replies-20261103")
ROLES = ["api", "worker", "mail-worker", "mail-worker-second", "dispatch", "monitor"]
PRIVATE = STAGE / "private"
ENV = dict(
    os.environ,
    FMG_AGENT_IMAGE="fmg-agent:sent-copy-20261020",
    FMG_AGENT_ENV_FILE="/etc/fmg-agent/multimail-20261017/service.env",
    FMG_AGENT_PG_ENV_FILE="/etc/fmg-agent/multimail-20261017/pg.env",
    FMG_AGENT_MAILBOXES_HOST_FILE="/etc/fmg-agent/multimail-20261017/mailboxes.json",
    FMG_AGENT_NETWORK="find-me-gamer-backend",
)


def run(*args, **kwargs):
    return subprocess.check_output(args, text=True, **kwargs)


def inspect(role):
    return json.loads(run("docker", "inspect", "fmg-agent-" + role + "-1"))[0]


def image(role):
    return "fmg-agent:replies-086-" + role + "-20261103"


def compose():
    base = json.loads((PRIVATE / "containers.json").read_text())["monitor"]
    labels = base["Config"]["Labels"]
    args = [
        "docker",
        "compose",
        "--profile",
        "second-mailbox",
        "--project-name",
        "fmg-agent",
        "--project-directory",
        labels["com.docker.compose.project.working_dir"],
    ]
    for file in labels["com.docker.compose.project.config_files"].split(","):
        assert Path(file).is_file()
        args += ["-f", file]
    return args


def runtime(action):
    return json.loads(
        subprocess.check_output(
            [
                "docker",
                "exec",
                "-i",
                "-e",
                "REPLY_ACTION=" + action,
                "fmg-agent-api-1",
                "python",
                "-",
            ],
            input=(STAGE / "runtime.py").read_text(),
            text=True,
        )
    )


def prepare():
    assert (
        not (PRIVATE / "before-state.json").exists()
        and not (PRIVATE / "applied").exists()
    )
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    before = {role: inspect(role) for role in ROLES}
    (PRIVATE / "containers.json").write_text(json.dumps(before))
    cmd = compose()
    old = json.loads(run(*cmd, "config", "--format", "json", env=ENV))
    (PRIVATE / "compose-before.json").write_text(json.dumps(old))
    for role, d in before.items():
        service = old["services"][role]
        assert service["image"] == d["Config"]["Image"], role + " image drift"
        if service.get("command") is not None:
            assert service["command"] == d["Config"]["Cmd"], role + " command drift"
        current_env = dict(v.split("=", 1) for v in d["Config"]["Env"])
        assert all(
            current_env.get(k) == str(v)
            for k, v in service.get("environment", {}).items()
        ), (role + " env drift")
        expected = {
            (
                v["target"],
                v["type"],
                (
                    v["source"]
                    if v["type"] == "bind"
                    else old["volumes"][v["source"]]["name"]
                ),
                not v.get("read_only", False),
            )
            for v in service["volumes"]
        }
        actual = {
            (
                v["Destination"],
                v["Type"],
                v["Source"] if v["Type"] == "bind" else v["Name"],
                v["RW"],
            )
            for v in d["Mounts"]
        }
        assert expected == actual, role + " mount drift"
        assert d["State"]["Running"]
    (STAGE / "compose.yaml").write_text(
        "services:\n" + "".join(f"  {r}:\n    image: {image(r)}\n" for r in ROLES)
    )
    new = json.loads(
        run(
            *cmd,
            "-f",
            str(STAGE / "compose.yaml"),
            "config",
            "--format",
            "json",
            env=ENV,
        )
    )
    expected = json.loads(json.dumps(old))
    for role in ROLES:
        expected["services"][role]["image"] = image(role)
    assert new == expected, "Unexpected Compose mutation"
    for key, name in [
        ("FMG_AGENT_ENV_FILE", "service.env"),
        ("FMG_AGENT_PG_ENV_FILE", "pg.env"),
        ("FMG_AGENT_MAILBOXES_HOST_FILE", "mailboxes.json"),
    ]:
        shutil.copyfile(ENV[key], PRIVATE / name)
    before_state = runtime("status")
    (PRIVATE / "before-state.json").write_text(json.dumps(before_state))
    print(json.dumps({"preflight": "passed", "state": before_state}), flush=True)


def build():
    before = json.loads((PRIVATE / "containers.json").read_text())
    manifest = json.loads((STAGE / "manifest.json").read_text())
    for role in ROLES:
        with (STAGE / (role + "-build.log")).open("w") as log:
            subprocess.run(
                [
                    "docker",
                    "build",
                    "--network=none",
                    "--build-arg",
                    "BASE=" + before[role]["Config"]["Image"],
                    "-t",
                    image(role),
                    str(STAGE / role),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
            )
        code = "import hashlib,json; from pathlib import Path; p=Path('/usr/local/lib/python3.13/site-packages/fmg_agent'); print(json.dumps({str(f.relative_to(p)):hashlib.sha256(f.read_bytes()).hexdigest() for f in p.rglob('*') if f.is_file() and '__pycache__' not in f.parts}))"
        previous = json.loads(
            run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python",
                before[role]["Config"]["Image"],
                "-c",
                code,
            )
        )
        current = json.loads(
            run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "--entrypoint",
                "python",
                image(role),
                "-c",
                code,
            )
        )
        assert all(current.get(k) == v for k, v in manifest[role].items()), (
            role + " staged hash mismatch"
        )
        assert all(
            current.get(k) == v for k, v in previous.items() if k not in manifest[role]
        ), (role + " unrelated package change")
        print(
            json.dumps(
                {"role": role, "image": image(role), "hash_verification": "passed"}
            ),
            flush=True,
        )


def apply():
    before = json.loads((PRIVATE / "containers.json").read_text())
    for role, d in before.items():
        assert inspect(role)["Id"] == d["Id"], "Container changed since preflight"
    assert not (PRIVATE / "applied").exists()
    print(json.dumps(runtime("hold")), flush=True)
    # Hold uses the sender fence and refuses active work. No SMTP/paid calls.
    held = runtime("status")
    (PRIVATE / "held-state.json").write_text(json.dumps(held))
    assert (
        held["active_sends"] == 0 and held["leases"] == 0 and held["running_jobs"] == 0
    )
    cmd = compose()
    with (PRIVATE / "database.dump").open("xb") as file:
        subprocess.run(
            cmd + ["run", "--rm", "-T", "backup"],
            env=ENV,
            stdout=file,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    assert (PRIVATE / "database.dump").stat().st_size > 0
    for role in ROLES:
        subprocess.run(
            ["docker", "update", "--restart=no", before[role]["Id"]],
            stdout=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(
            ["docker", "kill", "--signal=TERM", before[role]["Id"]],
            stdout=subprocess.DEVNULL,
            check=True,
        )
    deadline = time.monotonic() + 150
    while any(inspect(r)["State"]["Running"] for r in ROLES):
        if time.monotonic() > deadline:
            raise RuntimeError(
                "Warm drain incomplete; no force kill. Gates remain held."
            )
        time.sleep(2)
    path = Path(ENV["FMG_AGENT_MAILBOXES_HOST_FILE"])
    ownership = path.stat()
    data = json.loads(path.read_text())
    expected = json.loads((PRIVATE / "mailboxes.json").read_text())
    assert data == expected, "Registry drift"
    target = next(p for p in data["mailboxes"] if p["id"] == "second")
    assert target["smtp_from"].casefold() == "norestforthieves@ontologyplay.com"
    target["allowed_reply_templates"] = list(
        dict.fromkeys(
            target.get("allowed_reply_templates", []) + ["thieves-demo-access-reply"]
        )
    )
    tmp = path.with_suffix(".reply-new")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.chmod(0o600)
    os.chown(tmp, ownership.st_uid, ownership.st_gid)
    os.replace(tmp, path)
    subprocess.run(
        cmd + ["-f", str(STAGE / "compose.yaml"), "up", "-d", "--no-deps", *ROLES],
        env=ENV,
        check=True,
    )
    (PRIVATE / "applied").write_text("gates held; verify then restore prior runtime\n")
    print(
        "All six roles replaced; runtime gates still held for verification.", flush=True
    )


def verify():
    for role in ROLES:
        d = inspect(role)
        assert d["State"]["Running"] and d["Config"]["Image"] == image(role), (
            role + " not running expected image"
        )
    probes = [
        ("worker", "enrichment", None),
        ("mail-worker", "mail", "liminal"),
        ("mail-worker-second", "mail", "second"),
        ("dispatch", "dispatch", None),
        ("monitor", "monitor", "liminal"),
        ("monitor", "monitor", "second"),
    ]
    for service, role, mailbox in probes:
        args = [
            "docker",
            "exec",
            "fmg-agent-" + service + "-1",
            "python",
            "-m",
            "fmg_agent.role_health",
            role,
        ]
        if mailbox:
            args += ["--mailbox", mailbox]
        report = json.loads(run(*args))
        assert report["role"] == role
        print(
            json.dumps(
                {"service": service, "role": role, "mailbox": mailbox, "ready": True}
            ),
            flush=True,
        )
    run(
        "docker",
        "exec",
        "fmg-agent-api-1",
        "python",
        "-c",
        "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health',timeout=5)",
    )
    print(json.dumps({"service": "api", "http_health": "passed"}), flush=True)
    print(json.dumps(runtime("status")), flush=True)


def release():
    verify()
    expected = json.loads((PRIVATE / "held-state.json").read_text())
    prior = json.loads((PRIVATE / "before-state.json").read_text())
    expected.update(
        dispatch_enabled=prior["dispatch_enabled"], send_enabled=prior["send_enabled"]
    )
    result = run(
        "docker",
        "exec",
        "-i",
        "-e",
        "REPLY_ACTION=release",
        "-e",
        "REPLY_EXPECTED=" + json.dumps(expected),
        "fmg-agent-api-1",
        "python",
        "-",
        input=(STAGE / "runtime.py").read_text(),
    )
    (PRIVATE / "released-state.json").write_text(result)
    print(result, flush=True)


def rollback():
    # Restore configuration and binaries together. Preserve all database records.
    current = runtime("hold")
    print(json.dumps(current), flush=True)
    for role in ROLES:
        d = inspect(role)
        if d["State"]["Running"]:
            subprocess.run(
                ["docker", "update", "--restart=no", d["Id"]],
                stdout=subprocess.DEVNULL,
                check=True,
            )
            subprocess.run(
                ["docker", "kill", "--signal=TERM", d["Id"]],
                stdout=subprocess.DEVNULL,
                check=True,
            )
    deadline = time.monotonic() + 150
    while any(inspect(r)["State"]["Running"] for r in ROLES):
        if time.monotonic() > deadline:
            raise RuntimeError("Rollback drain incomplete; gates remain held")
        time.sleep(2)
    path = Path(ENV["FMG_AGENT_MAILBOXES_HOST_FILE"])
    ownership = path.stat()
    tmp = path.with_suffix(".reply-rollback")
    shutil.copyfile(PRIVATE / "mailboxes.json", tmp)
    tmp.chmod(0o600)
    os.chown(tmp, ownership.st_uid, ownership.st_gid)
    os.replace(tmp, path)
    subprocess.run(compose() + ["up", "-d", "--no-deps", *ROLES], env=ENV, check=True)
    print(
        "Prior images and registry restored. Gates held pending readiness and prior-state restoration.",
        flush=True,
    )


if __name__ == "__main__":
    os.umask(0o077)
    {
        "prepare": prepare,
        "build": build,
        "apply": apply,
        "verify": verify,
        "release": release,
        "rollback": rollback,
    }[sys.argv[1]]()
