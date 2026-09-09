"""Launcher for unchanged pinned application modules with HTTP fixture transport."""

import json
import logging
import os
from pathlib import Path
import sys

from fixture import destination_allowed, start_server

ANALYZE_REVISION = "5706ad76f924991b80ee2a7fb6806528366be5ce"
OUTREACH_REVISIONS = {"ece2e9d9558dfe057dc40ad58bd98a86e3149dd5", ANALYZE_REVISION,
                     "28595d84805137dabbdadd31f26f9fa5b51d988b",
                     "6d8425a99d7bd050424904a1492166b14f2ee5ac"}


def install_smtp_capture(private, state_directory):
    if private["backend_revision"] not in OUTREACH_REVISIONS:
        return None
    from smtp_capture import capture_gateway

    gateway = capture_gateway(state_directory)
    from app.workers import activity_send_tasks, outreach_tasks

    # Keep real worker/claim/limiter/MIME/error logic. Only construction of its
    # real SMTPGateway is bound to the socket-free resolver/connection factory.
    activity_send_tasks.SMTPGateway = lambda: gateway
    outreach_tasks.SMTPGateway = lambda: gateway
    return gateway


def configure():
    global destination_allowed, start_server
    from app.core.security import hash_workspace_key

    private = json.loads(Path("/private/client.json").read_text())
    if private["backend_revision"] == ANALYZE_REVISION:
        import importlib.util

        spec = importlib.util.spec_from_file_location("analyze_runtime", "/analyze-harness/runtime.py")
        extension = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(extension)
        destination_allowed, start_server = extension.install()
        os.environ["STEAM_STORE_BASE_URL"] = "http://127.0.0.1:18081/steam"
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
        smtp_gateway = install_smtp_capture(private, "/state")
        start_server("/state")
        if action == "api":
            import uvicorn
            from app.main import create_app

            uvicorn.run(
                create_app(smtp_gateway=smtp_gateway),
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
