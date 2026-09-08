"""Launcher for unchanged pinned application modules with HTTP fixture transport."""

import json
import logging
import os
from pathlib import Path
import sys

from fixture import destination_allowed, start_server


def configure():
    from app.core.security import hash_workspace_key

    private = json.loads(Path("/private/client.json").read_text())
    os.environ["WORKSPACE_ACCESS_KEY_HASH"] = hash_workspace_key(
        private["workspace_key"]
    )
    import httpx

    original = httpx.HTTPTransport.handle_request

    def guarded(self, request):
        if not destination_allowed(request.url):
            raise httpx.ConnectError(
                "Test fixture destination rejected", request=request
            )
        return original(self, request)

    httpx.HTTPTransport.handle_request = guarded
    from app.workers.celery_app import celery_app

    celery_app.conf.task_default_queue = private["queue"]
    celery_app.conf.task_routes = {"find_me_gamer.*": {"queue": private["queue"]}}
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)
    return private, celery_app


def main():
    private, celery_app = configure()
    action = sys.argv[1]
    if action == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("/app/alembic.ini"), "head")
    elif action in {"api", "worker"}:
        start_server("/state")
        if action == "api":
            import uvicorn
            from app.main import create_app

            uvicorn.run(
                create_app(),
                host="0.0.0.0",
                port=8000,
                access_log=False,
                log_level="warning",
                proxy_headers=False,
            )
        else:
            celery_app.worker_main(
                [
                    "worker",
                    "--loglevel=WARNING",
                    "--concurrency=1",
                    "--pool=solo",
                    "--queues=" + private["queue"],
                    "--without-gossip",
                    "--without-mingle",
                    "--without-heartbeat",
                ]
            )
    else:
        raise ValueError("Unknown fixture runtime action")


if __name__ == "__main__":
    main()
