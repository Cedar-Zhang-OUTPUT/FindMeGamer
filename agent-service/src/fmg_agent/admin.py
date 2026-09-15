"""Local server administration; never accepts provider keys in command arguments."""

import argparse
import json
import sys

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from .auth import VALID_SCOPES, issue_token, revoke_token
from .config import Settings
from .db import database


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m fmg_agent.admin")
    token = parser.add_subparsers(dest="group", required=True).add_parser("token")
    commands = token.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--label", required=True)
    create.add_argument("--scope", action="append", choices=sorted(VALID_SCOPES))
    revoke = commands.add_parser("revoke")
    revoke.add_argument("id")
    args = parser.parse_args(argv)
    engine = None
    try:
        engine, sessions = database(Settings())
        with sessions() as session:
            if args.command == "create":
                issued = issue_token(
                    session, label=args.label, scopes=args.scope or ["read"]
                )
                print(json.dumps({"id": issued.id, "token": issued.token}))
            else:
                if not revoke_token(session, args.id):
                    print("Token ID not found.", file=sys.stderr)
                    return 1
                print(json.dumps({"id": args.id, "revoked": True}))
        return 0
    except (ValidationError, ValueError):
        print(
            "Invalid configuration or token parameters; use an isolated agent database.",
            file=sys.stderr,
        )
        return 2
    except SQLAlchemyError:
        print(
            "Service storage is unavailable; check connectivity and migrations.",
            file=sys.stderr,
        )
        return 5
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
