"""One-time EC2 bootstrap from the stopped native service; run locally on EC2 as root.

Never prints credentials. Refuses existing target configuration/database/role.
Only copies provider configuration; does not copy legacy business data or start it.
"""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-container", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply or os.geteuid() != 0:
        parser.error("Requires root and explicit --apply")
    target = Path("/etc/fmg-agent")
    if target.exists():
        parser.error("Target configuration already exists; inspect, do not overwrite")
    source = json.loads(run(["docker", "inspect", args.source_container]).stdout)[0]
    if source["State"]["Running"]:
        parser.error("Legacy source must remain stopped")
    mounts = source["Mounts"]
    key = next(m for m in mounts if m["Destination"] == "/etc/find-me-gamer/master.key")
    password = secrets.token_urlsafe(36)
    target.mkdir(mode=0o700)
    # Temporary old environment stays root-readable and is removed after export.
    with tempfile.TemporaryDirectory(prefix="fmg-bootstrap-", dir=target) as temporary:
        envfile = Path(temporary) / "legacy.env"
        envfile.write_text("\n".join(source["Config"]["Env"]) + "\n")
        envfile.chmod(0o600)
        script = """
import json, os, sys
from pathlib import Path
from sqlalchemy import create_engine, text
from app.core.crypto import SecretCipher, EncryptedValue
from app.integrations.gemini_email import DEFAULT_GEMINI_EMAIL_MODEL
engine=create_engine(os.environ['DATABASE_URL'])
cipher=SecretCipher.from_file(Path('/etc/find-me-gamer/master.key'))
values={}
with engine.connect() as connection:
    for row in connection.execute(text('SELECT service,ciphertext,nonce FROM service_secrets')):
        if row.service in ('youtube','x','google_ai','steam'):
            values[row.service]=cipher.decrypt(EncryptedValue(bytes(row.ciphertext),bytes(row.nonce)))
assert values.get('youtube') and values.get('x') and values.get('google_ai'), 'Required provider configuration missing'
# Run only against the administrator connection already owned by the old service.
with engine.connect().execution_options(isolation_level='AUTOCOMMIT') as connection:
    assert not connection.scalar(text("SELECT 1 FROM pg_database WHERE datname='find_me_gamer_agent'")), 'New DB already exists'
    assert not connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname='fmg_agent'")), 'New role already exists'
    from psycopg import sql
    password=sys.stdin.read().strip()
    connection.exec_driver_sql(sql.SQL('CREATE ROLE fmg_agent LOGIN PASSWORD {}').format(sql.Literal(password)).as_string())
    connection.exec_driver_sql('CREATE DATABASE find_me_gamer_agent OWNER fmg_agent')
values['gemini_model']=DEFAULT_GEMINI_EMAIL_MODEL
values['redis_url']=os.environ.get('REDIS_URL','redis://redis:6379/0')
print(json.dumps(values))
"""
        # Script supplied as argument contains no secrets; password travels via stdin.
        exported = run(
            [
                "docker",
                "run",
                "--rm",
                "-i",
                "--network",
                "find-me-gamer-backend",
                "--env-file",
                str(envfile),
                "-v",
                key["Source"] + ":" + key["Destination"] + ":ro",
                "--entrypoint",
                "python",
                source["Config"]["Image"],
                "-c",
                script,
            ],
            input=password.encode(),
        )
        values = json.loads(exported.stdout)
    config = {
        "FMG_AGENT_DATABASE_URL": f"postgresql+psycopg://fmg_agent:{password}@postgres:5432/find_me_gamer_agent",
        "FMG_AGENT_BROKER_URL": values["redis_url"],
        "FMG_AGENT_YOUTUBE_API_KEY": values["youtube"],
        "FMG_AGENT_X_BEARER_TOKEN": values["x"],
        "FMG_AGENT_STEAM_API_KEY": values.get("steam", ""),
        "FMG_AGENT_GEMINI_API_KEY": values["google_ai"],
        "FMG_AGENT_GEMINI_MODEL": values["gemini_model"],
        "FMG_AGENT_EMAIL_RETENTION_DAYS": "30",
    }
    pg = {
        "PGHOST": "postgres",
        "PGPORT": "5432",
        "PGUSER": "fmg_agent",
        "PGPASSWORD": password,
        "PGDATABASE": "find_me_gamer_agent",
    }
    for filename, items in [("service.env", config), ("pg.env", pg)]:
        # Compose single-quoted env values do not interpolate dollar signs.
        content = (
            "\n".join(
                k + "='" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
                for k, v in items.items()
            )
            + "\n"
        )
        path = target / filename
        with path.open("x") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(content)
    print(
        json.dumps(
            {
                "created_database": "find_me_gamer_agent",
                "config_directory": str(target),
                "configured": {
                    key: bool(values.get(key))
                    for key in ("youtube", "x", "steam", "google_ai")
                },
                "gemini_model": values["gemini_model"],
                "smtp_configured": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit(
            "Bootstrap failed; inspect protected server state. No credentials printed. Do not blindly rerun."
        ) from None
