"""Run inside the current API; never sends, retries, or clears safety holds."""

import hashlib, json, os
from sqlalchemy import select, text
from fmg_agent.config import Settings
from fmg_agent.db import database
from fmg_agent.mail_runtime import MailRuntime

cfg = Settings()
e, ss = database(cfg)


def status(s):
    runtime = s.get(MailRuntime, 1)
    safe = s.execute(
        text("select sender,reason,paused_at from email_sender_safety order by sender")
    ).all()
    return {
        "dispatch_enabled": runtime.dispatch_enabled,
        "send_enabled": runtime.send_enabled,
        "active_sends": s.scalar(
            text("select count(*) from email_sends where state='sending'")
        ),
        "running_jobs": s.scalar(
            text("select count(*) from email_jobs where state='running'")
        ),
        "leases": s.scalar(
            text("select count(*) from email_send_gates where lease_id is not null")
        ),
        "pending_sends": s.scalar(
            text(
                "select count(*) from outreach_recipients r join outreach_tasks t on r.task_id=t.id where t.state='sending' and not exists(select 1 from email_sends s where s.preview_id=r.preview_id)"
            )
        ),
        "sends": dict(
            s.execute(
                text("select state,count(*) from email_sends group by state")
            ).all()
        ),
        "tasks": dict(
            s.execute(
                text("select state,count(*) from outreach_tasks group by state")
            ).all()
        ),
        "safety_hash": hashlib.sha256(
            json.dumps([list(r) for r in safe], default=str).encode()
        ).hexdigest(),
    }


with ss() as s:
    action = os.environ.get("REPLY_ACTION", "status")
    if action == "hold":
        s.execute(text("SET LOCAL lock_timeout='5s'"))
        row = s.scalar(select(MailRuntime).where(MailRuntime.id == 1).with_for_update())
        before = status(s)
        assert (
            before["active_sends"] == 0
            and before["leases"] == 0
            and before["running_jobs"] == 0
        ), "In-flight work; no cutover"
        assert (
            before["pending_sends"] == 0
        ), "Pending batch work; inspect before cutover"
        row.dispatch_enabled = row.send_enabled = False
        s.commit()
    elif action == "release":
        s.execute(text("SET LOCAL lock_timeout='5s'"))
        row = s.scalar(select(MailRuntime).where(MailRuntime.id == 1).with_for_update())
        current = status(s)
        expected = json.loads(os.environ["REPLY_EXPECTED"])
        assert not row.send_enabled and not row.dispatch_enabled
        assert (
            current["active_sends"] == 0
            and current["leases"] == 0
            and current["running_jobs"] == 0
            and current["pending_sends"] == 0
        )
        assert all(
            current[k] == expected[k] for k in ["sends", "tasks", "safety_hash"]
        ), "Mailbox/task state changed during cutover"
        row.dispatch_enabled = expected["dispatch_enabled"]
        row.send_enabled = expected["send_enabled"]
        s.commit()
    print(json.dumps(status(s), default=str))
