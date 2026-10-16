"""Container-local readiness, refreshed only by initialized role work loops."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import time

SCHEMA = "0013_mail_runtime"


def identity(settings, role, mailbox):
    from .worker import queue_for_mailbox

    if role not in {"enrichment", "mail", "dispatch", "monitor"}:
        raise ValueError("Unknown role")
    if (role in {"mail", "monitor"}) != bool(mailbox):
        raise ValueError("Mailbox/role mismatch")
    queue = (
        queue_for_mailbox(mailbox)
        if role == "mail"
        else ("fmg_enrichment" if role == "enrichment" else None)
    )
    return dict(
        role=role,
        mailbox=mailbox,
        schema=SCHEMA,
        queue=queue,
        concurrency={"mail": 2, "enrichment": 4}.get(role),
        database=sha256(settings.database_url.encode()).hexdigest(),
    )


def path_for(settings, role, mailbox=None):
    info = identity(settings, role, mailbox)
    root = Path(os.environ.get("FMG_AGENT_ROLE_HEALTH_DIR", "/tmp/fmg-agent-health"))
    return root / info["database"] / f'{role}-{mailbox or "global"}.json'


def process_start(pid):
    # Linux container PID reuse must not revive an old ready file. macOS is for
    # native rehearsal only; ps also verifies the owner still exists there.
    stat = Path(f"/proc/{pid}/stat")
    if Path("/proc").is_dir():
        return stat.read_text().rsplit(")", 1)[1].split()[19]
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "lstart="],
        text=True,
        capture_output=True,
        check=False,
    ).stdout.strip()
    if not result:
        raise ValueError("Process exited")
    return result


def record(settings, role, mailbox=None, *, mode="local-ready"):
    data = dict(
        identity(settings, role, mailbox),
        pid=os.getpid(),
        process_start=process_start(os.getpid()),
        time=time.time(),
        mode=mode,
    )
    path = path_for(settings, role, mailbox)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream)
    temporary.replace(path)
    return data


def clear(settings, role, mailbox=None):
    path_for(settings, role, mailbox).unlink(missing_ok=True)


def probe(settings, role, mailbox=None):
    data = json.loads(path_for(settings, role, mailbox).read_text())
    expected = identity(settings, role, mailbox)
    max_age = 30
    if role == "monitor":
        from .mailboxes import MailboxRegistry

        max_age = max(
            30,
            MailboxRegistry.load(settings)
            .select(mailbox, allow_legacy=False)
            .imap_poll_seconds
            * 2
            + 10,
        )
    if (
        any(data.get(key) != value for key, value in expected.items())
        or not 0 <= time.time() - data["time"] <= max_age
        or data["process_start"] != process_start(data["pid"])
    ):
        raise ValueError("Role readiness is missing, stale or mismatched")
    if role == "mail":
        from .mailboxes import MailboxRegistry

        registry = MailboxRegistry.load(settings)
        if not registry._ready(registry.select(mailbox, allow_legacy=False)):
            raise ValueError("Mailbox local configuration is incomplete")
    return data


def main():
    from .config import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role")
    parser.add_argument("--mailbox")
    args = parser.parse_args()
    try:
        print(json.dumps(probe(Settings(), args.role, args.mailbox)))
    except Exception:
        raise SystemExit("Role is not locally ready") from None


if __name__ == "__main__":
    main()
