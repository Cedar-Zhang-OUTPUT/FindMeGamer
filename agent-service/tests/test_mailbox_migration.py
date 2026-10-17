from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from test_email_sending import sending, headers
from test_mailbox_outreach import payload
from test_migrations import migrate


@pytest.mark.parametrize("apply", [False, True])
def test_large_frozen_previews_use_bounded_memory(sending, apply):
    import gc
    import tracemalloc
    from fmg_agent.email.identity import backfill_mailboxes
    from fmg_agent.email.models import EmailPreview

    app, _, owner, _, _ = sending
    with app.state.sessions() as session:
        for number in range(40):
            session.add(
                EmailPreview(
                    id=f"large-{number}",
                    token_id=owner.id,
                    template_id="game-outreach",
                    template_version="5",
                    message={
                        "from": "publisher@example.com",
                        "html": "x" * (256 * 1024),
                    },
                )
            )
        session.commit()
    gc.collect()
    tracemalloc.start()
    try:
        with app.state.sessions() as session:
            result = backfill_mailboxes(session, app.state.mailboxes, apply=apply)
            assert result["previews"] == 40 and result["unchanged"]
            session.commit()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024 * 1024, f"Frozen body materialization peaked at {peak} bytes"


@pytest.mark.parametrize("missing", [None, "absent"])
def test_orphan_missing_sender_is_preserved_but_never_sendable(sending, missing):
    from fmg_agent.email.identity import backfill_mailboxes
    from fmg_agent.email.models import EmailPreview, EmailSend
    from test_email_sending import preview, send

    app, client, owner, _, _ = sending
    preview_id = preview(client, owner).json()["data"]["id"]
    with app.state.sessions() as session:
        row = session.get(EmailPreview, preview_id)
        message = dict(row.message)
        if missing is None:
            message["from"] = None
        else:
            message.pop("from")
        row.message, row.mailbox_id = message, None
        session.commit()
        before = deepcopy(row.message)
        for apply in (False, True, True):
            outcome = backfill_mailboxes(session, app.state.mailboxes, apply=apply)
            assert outcome["preserved_unsendable_previews"] == 1
            assert outcome["previews"] == 0
            assert outcome["unchanged"]
            session.commit()
            assert row.message == before and row.mailbox_id is None
    app.state.smtp_transport = lambda *args: pytest.fail("orphan reached transport")
    response = send(client, owner, preview_id)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "mailbox_backfill_required"
    with app.state.sessions() as session:
        assert session.scalar(select(EmailSend)) is None


@pytest.mark.parametrize(
    "association", ["task", "send", "identity", "unknown_sender", "malformed_message"]
)
def test_missing_sender_exemption_never_hides_associations(sending, association):
    from fmg_agent.email.identity import backfill_mailboxes
    from fmg_agent.email.models import EmailPreview, EmailSend
    from test_email_sending import preview

    app, client, owner, _, _ = sending
    if association == "task":
        client.post("/v1/outreach/tasks", headers=headers(owner), json=payload())
    else:
        preview(client, owner)
    with app.state.sessions() as session:
        row = session.scalar(select(EmailPreview))
        row.message = {
            **row.message,
            "from": "unknown@example.com" if association == "unknown_sender" else None,
        }
        if association == "malformed_message":
            row.message = []
        if association != "identity":
            row.mailbox_id = None
        if association == "send":
            session.add(
                EmailSend(
                    token_id=row.token_id,
                    preview_id=row.id,
                    idempotency_key="historical",
                    state="unknown",
                )
            )
        session.commit()
        with pytest.raises(ValueError, match="unmapped"):
            backfill_mailboxes(session, app.state.mailboxes, apply=True)


def test_disabled_historical_sender_maps_without_enabling_delivery(sending):
    from fmg_agent.email.identity import backfill_mailboxes, preview_mailbox
    from fmg_agent.email.models import EmailPreview
    from fmg_agent.errors import ApiError
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile
    from test_email_sending import preview

    app, client, owner, _, _ = sending
    preview(client, owner)
    registry = MailboxRegistry(
        app.state.settings,
        [
            *app.state.mailboxes.profiles(),
            MailboxProfile(
                id="legacy-retired", enabled=False, smtp_from="retired@example.com"
            ),
            MailboxProfile(id="second", enabled=False),
        ],
        legacy=False,
    )
    with app.state.sessions() as session:
        row = session.scalar(select(EmailPreview))
        row.message = {**row.message, "from": "retired@example.com"}
        row.mailbox_id = None
        session.commit()
        outcome = backfill_mailboxes(session, registry, apply=True)
        session.commit()
        assert outcome["unchanged"] and row.mailbox_id == "legacy-retired"
        with pytest.raises(ApiError) as failure:
            preview_mailbox(session, row, registry)
        assert failure.value.code == "mailbox_disabled"


def test_registry_profiles_include_disabled_without_discovery(sending):
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile

    app, _, _, _, _ = sending
    active = MailboxProfile(id="one", smtp_from="one@example.com")
    disabled = MailboxProfile(id="two", enabled=False)
    registry = MailboxRegistry(app.state.settings, [active, disabled], legacy=False)
    assert registry.profiles() == (active, disabled)


@pytest.mark.parametrize(
    "identity,sender",
    [("ontologyplay", "other@example.com"), ("renamed", "PUBLISHER@example.com")],
)
def test_registered_sender_identity_cannot_be_reassigned(sending, identity, sender):
    from fmg_agent.email.identity import register_identities
    from fmg_agent.email.models import MailboxIdentity
    from fmg_agent.errors import ApiError
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile

    app, _, _, _, _ = sending
    with app.state.sessions() as session:
        register_identities(session, app.state.mailboxes)
        session.commit()
        changed = MailboxRegistry(
            app.state.settings,
            [MailboxProfile(id=identity, smtp_from=sender)],
            legacy=False,
        )
        with pytest.raises(ApiError) as failure:
            register_identities(session, changed)
        assert failure.value.code == "mailbox_identity_conflict"
        assert (
            session.get(MailboxIdentity, "ontologyplay").sender
            == "publisher@example.com"
        )


def test_mixed_known_task_senders_abort_without_identity_writes(sending):
    from fmg_agent.email.identity import backfill_mailboxes
    from fmg_agent.email.models import EmailPreview, MailboxIdentity
    from fmg_agent.outreach import OutreachTask, OutreachRecipient
    from fmg_agent.mailboxes import MailboxRegistry, MailboxProfile

    app, client, owner, _, _ = sending
    client.post("/v1/outreach/tasks", headers=headers(owner), json=payload())
    with app.state.sessions() as session:
        task = session.scalar(select(OutreachTask))
        task.mailbox_id = None
        session.scalar(select(EmailPreview)).mailbox_id = None
        extra = EmailPreview(
            id="mixed-preview",
            token_id=task.token_id,
            template_id="game-outreach",
            template_version="5",
            message={"from": "two@example.com"},
        )
        session.add(extra)
        session.flush()
        session.add(
            OutreachRecipient(
                id="mixed-recipient",
                task_id=task.id,
                creator_id="two",
                preview_id=extra.id,
            )
        )
        session.commit()
        registry = MailboxRegistry(
            app.state.settings,
            [
                MailboxProfile(id="ontologyplay", smtp_from="publisher@example.com"),
                MailboxProfile(id="two", smtp_from="two@example.com"),
            ],
            legacy=False,
        )
        with pytest.raises(ValueError, match="mixed"):
            backfill_mailboxes(session, registry, apply=True)
        session.commit()
        assert session.get(MailboxIdentity, "two") is None
        assert all(
            row.mailbox_id is None for row in session.scalars(select(EmailPreview))
        )


def test_mixed_or_unmapped_from_aborts_backfill(sending):
    from fmg_agent.email.identity import backfill_mailboxes
    from fmg_agent.email.models import EmailPreview, MailboxIdentity
    from fmg_agent.outreach import OutreachTask

    app, client, owner, _, _ = sending
    client.post("/v1/outreach/tasks", headers=headers(owner), json=payload())
    with app.state.sessions() as session:
        task = session.scalar(select(OutreachTask))
        task.mailbox_id = None
        preview = session.scalar(select(EmailPreview))
        preview.mailbox_id = None
        preview.message = {**preview.message, "from": "unmapped@example.com"}
        session.commit()
        with pytest.raises(ValueError, match="unmapped"):
            backfill_mailboxes(session, app.state.mailboxes, apply=True)
        session.commit()
        assert session.get(OutreachTask, task.id).mailbox_id is None
        assert session.get(EmailPreview, preview.id).mailbox_id is None


@pytest.mark.postgres
def test_backfill_preserves_frozen_approval():
    from fmg_agent.config import Settings
    from fmg_agent.email.identity import backfill_mailboxes
    from fmg_agent.mailboxes import MailboxRegistry

    url = os.environ.get("FMG_AGENT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set FMG_AGENT_TEST_DATABASE_URL for isolated PostgreSQL checks")
    engine = create_engine(url)
    assert engine.url.database == "find_me_gamer_agent_test"
    schema = "mailbox_test_" + uuid.uuid4().hex
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = create_engine(url, connect_args={"options": f"-c search_path={schema}"})
    try:
        old = migrate(url, schema, revision="0011_bounce_retry")
        assert old.returncode == 0, old.stderr
        message = {
            "from": "publisher@example.com",
            "to": "alice@example.com",
            "text": "frozen",
            "images": ["frozen-image"],
        }
        with scoped.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO access_tokens (id,digest,label,scopes,created_at) VALUES ('owner',:digest,'old','[]',CURRENT_TIMESTAMP)"
                ),
                {"digest": "f" * 64},
            )
            conn.execute(
                text(
                    "INSERT INTO email_previews (id,token_id,template_id,template_version,message,created_at) VALUES ('preview','owner','game-outreach','5',:message,CURRENT_TIMESTAMP)"
                ),
                {"message": json.dumps(message)},
            )
            conn.execute(
                text(
                    "INSERT INTO email_previews (id,token_id,template_id,template_version,message,created_at) VALUES ('single-preview','owner','game-outreach','5',:message,CURRENT_TIMESTAMP)"
                ),
                {"message": json.dumps({**message, "to": "single@example.com"})},
            )
            conn.execute(
                text(
                    "INSERT INTO outreach_tasks (id,token_id,idempotency_key,fingerprint,revision,state,name,run_id,template) VALUES ('task','owner','old-key',:fingerprint,:revision,'blocked','Old','run','{}')"
                ),
                {"fingerprint": "a" * 64, "revision": "b" * 64},
            )
            conn.execute(
                text(
                    "INSERT INTO outreach_recipients (id,task_id,creator_id,preview_id) VALUES ('recipient','task','alice','preview')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO email_sends (id,token_id,preview_id,idempotency_key,state,code,diagnostics,created_at,updated_at) VALUES ('send','owner','preview','send-key','unknown','lost','{}',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
                )
            )

        def frozen():
            with scoped.connect() as conn:
                return [
                    list(conn.execute(text(query)))
                    for query in [
                        "SELECT fingerprint,revision,state,idempotency_key,template FROM outreach_tasks",
                        "SELECT message FROM email_previews ORDER BY id",
                        "SELECT id,preview_id,idempotency_key,state,code,diagnostics FROM email_sends",
                    ]
                ]

        before = deepcopy(frozen())
        upgraded = migrate(url, schema)
        assert upgraded.returncode == 0, upgraded.stderr
        from fmg_agent.outreach import view

        before_summary = view(sessionmaker(scoped), "task", "owner", summary=True)
        registry = MailboxRegistry.load(
            Settings(database_url=url, smtp_from="publisher@example.com")
        )
        tool = (
            Path(__file__).resolve().parents[2]
            / "deploy/agent-services/mailbox_preflight.py"
        )
        env = dict(
            os.environ,
            FMG_AGENT_DATABASE_URL=url,
            FMG_AGENT_SMTP_FROM="publisher@example.com",
            PGOPTIONS=f"-c search_path={schema}",
        )
        refused = subprocess.run(
            [sys.executable, str(tool), "--apply"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert refused.returncode == 2
        assert "quiescent" in refused.stderr
        dry_cli = subprocess.run(
            [sys.executable, str(tool)], env=env, capture_output=True, text=True
        )
        assert dry_cli.returncode == 0, dry_cli.stderr
        assert json.loads(dry_cli.stdout)["applied"] is False
        with sessionmaker(scoped)() as session:
            dry = backfill_mailboxes(session, registry)
            assert dry["previews"] == 2 and dry["tasks"] == 1
            assert session.scalar(text("SELECT mailbox_id FROM email_previews")) is None
            outcome = backfill_mailboxes(session, registry, apply=True)
            assert outcome["unchanged"] is True
            session.commit()
            assert session.scalars(
                text("SELECT mailbox_id FROM email_previews ORDER BY id")
            ).all() == ["ontologyplay", "ontologyplay"]
            assert (
                session.scalar(text("SELECT mailbox_id FROM outreach_tasks"))
                == "ontologyplay"
            )
        after_summary = view(sessionmaker(scoped), "task", "owner", summary=True)
        assert {
            key: value for key, value in after_summary.items() if key != "mailbox_id"
        } == {
            key: value for key, value in before_summary.items() if key != "mailbox_id"
        }
        applied_cli = subprocess.run(
            [sys.executable, str(tool), "--apply", "--quiescent"],
            env=env,
            capture_output=True,
            text=True,
        )
        assert applied_cli.returncode == 0, applied_cli.stderr
        assert json.loads(applied_cli.stdout)["unchanged"] is True
        assert frozen() == before
    finally:
        scoped.dispose()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()
