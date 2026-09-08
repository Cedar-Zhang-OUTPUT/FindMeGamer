"""Test-only launch wrapper. No application behavior or provider fallback changes."""

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread


class ProviderFixture(BaseHTTPRequestHandler):
    counts = {"youtube_search": 0, "youtube_channels": 0, "x_search": 0}

    def log_message(self, *args):
        pass  # Never log request headers, query parameters or provider credentials.

    def do_GET(self):
        from urllib.parse import urlsplit

        path = urlsplit(self.path).path
        if path == "/stats":
            body = dict(self.counts)
        elif path == "/youtube/v3/search":
            self.counts["youtube_search"] += 1
            body = {
                "items": [
                    {
                        "id": {"videoId": "smoke-video"},
                        "snippet": {
                            "channelId": "UCsmoke123",
                            "channelTitle": "Fixture creator",
                            "title": "Fixture gameplay metadata",
                        },
                    }
                ],
                "nextPageToken": "do-not-follow",
            }
        elif path == "/youtube/v3/channels":
            self.counts["youtube_channels"] += 1
            body = {
                "items": [
                    {
                        "id": "UCsmoke123",
                        "snippet": {"title": "Fixture creator", "country": "US"},
                        "statistics": {"subscriberCount": "1000"},
                    }
                ]
            }
        elif path == "/x/2/tweets/search/recent":
            self.counts["x_search"] += 1
            body = {
                "data": [
                    {
                        "id": "901",
                        "author_id": "902",
                        "text": "Fixture indie game metadata",
                        "lang": "en",
                    }
                ],
                "includes": {
                    "users": [
                        {
                            "id": "902",
                            "name": "Fixture X creator",
                            "username": "fixture",
                            "public_metrics": {"followers_count": 100},
                        }
                    ]
                },
                "meta": {"result_count": 1, "next_token": "do-not-follow"},
            }
        else:
            self.send_error(404)
            return
        content = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def configure():
    mode = os.environ.get("FMG_SMOKE_MODE")
    if mode not in {"fixture", "live"}:
        raise ValueError("An explicit smoke mode is required.")
    config = json.loads(Path("/private/client.json").read_text())
    from app.core.security import hash_workspace_key

    os.environ["WORKSPACE_ACCESS_KEY_HASH"] = hash_workspace_key(
        config["workspace_key"]
    )
    if mode == "fixture":
        os.environ["YOUTUBE_API_BASE_URL"] = "http://127.0.0.1:18081/youtube/v3"
        os.environ["X_API_BASE_URL"] = "http://127.0.0.1:18081/x/2"
        server = ThreadingHTTPServer(("127.0.0.1", 18081), ProviderFixture)
        Thread(target=server.serve_forever, daemon=True).start()
    else:
        os.environ["YOUTUBE_API_BASE_URL"] = "https://www.googleapis.com/youtube/v3"
        os.environ["X_API_BASE_URL"] = "https://api.x.com/2"


class SmokeDispatcher:
    def dispatch(self, batch_id):
        from app.workers.celery_app import celery_app

        celery_app.send_task(
            "find_me_gamer.discovery.run_batch",
            args=[str(batch_id)],
            queue="discovery-smoke",
            retry=False,
        )


def main():
    import sys

    configure()
    action = sys.argv[1]
    if action == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("/app/alembic.ini"), "head")
    elif action == "api":
        import uvicorn
        from app.main import create_app

        uvicorn.run(
            create_app(discovery_dispatcher=SmokeDispatcher()),
            host="0.0.0.0",
            port=8000,
            access_log=False,
            log_level="warning",
        )
    elif action == "worker":
        from app.workers.celery_app import celery_app

        celery_app.worker_main(
            [
                "worker",
                "--loglevel=WARNING",
                "--concurrency=1",
                "--pool=solo",
                "--queues=discovery-smoke",
            ]
        )
    else:
        raise ValueError("Unknown smoke action.")


if __name__ == "__main__":
    main()
