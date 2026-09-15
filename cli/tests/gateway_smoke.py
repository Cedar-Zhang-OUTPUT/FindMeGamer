"""Compiled CLI -> real local HTTP gateway -> simulated platform transport.

Run with the agent-service virtualenv. No company credentials or external calls.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

import httpx
import uvicorn

from fmg_agent.app import create_app
from fmg_agent.auth import issue_token
from fmg_agent.config import Settings
from fmg_agent.db import Base


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', type=Path, required=True)
    binary = parser.parse_args().binary.resolve()
    with tempfile.TemporaryDirectory(prefix='fmg-cli-smoke-') as temporary:
        root = Path(temporary)
        app = create_app(Settings(database_url=f'sqlite:///{root / "test.sqlite"}', youtube_api_key='fake-platform-key'))
        Base.metadata.create_all(app.state.engine)
        with app.state.sessions() as session:
            issued = issue_token(session, label='local-cli-test', scopes=['read'])
        calls = []
        def upstream(request):
            assert request.url.host == 'youtube.googleapis.com'
            assert request.url.params['key'] == 'fake-platform-key'
            calls.append(dict(request.url.params))
            next_cursor = 'page2' if 'pageToken' not in request.url.params else None
            data = {'items': [{'id': 'sample', 'future_field': {'value': True}}]}
            if next_cursor:
                data['nextPageToken'] = next_cursor
            return httpx.Response(200, json=data)
        app.state.provider_transport = httpx.MockTransport(upstream)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))
        thread = threading.Thread(target=server.run, kwargs={'sockets': [sock]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if time.monotonic() > deadline:
                    raise RuntimeError('Local smoke gateway did not start')
                time.sleep(0.05)
            env = dict(os.environ, FMG_CONFIG=str(root / 'config.json'))
            def run(args, stdin=''):
                result = subprocess.run([str(binary), *args], input=stdin, env=env, text=True, capture_output=True, timeout=20)
                assert result.returncode == 0, f'{args[:2]} exited {result.returncode}: {result.stderr}'
                assert issued.token not in result.stdout + result.stderr
                assert 'fake-platform-key' not in result.stdout + result.stderr
                return [json.loads(line) for line in result.stdout.splitlines()]
            assert run(['auth','login','--server',f'http://127.0.0.1:{port}','--token-stdin'],issued.token)[0]['authenticated']
            inventory = run(['youtube','operations'])[0]['data']
            assert any(row['id']=='search.list' for row in inventory)
            assert 'relevanceLanguage' in run(['youtube','describe','search.list'])[0]['data']['parameters']
            single = run(['youtube','call','search.list','--params','{"part":"snippet"}'])
            assert len(calls) == 1
            assert single[0]['data']['items'][0]['future_field']['value'] is True
            pages = run(['youtube','call','search.list','--params','{"part":"snippet"}','--max-pages','2'])
            assert len(pages) == 2 and len(calls) == 3
            assert calls[-1]['pageToken'] == 'page2'
            run(['auth','check'])
            assert run(['auth','logout'])[0]['logged_out']
            assert not (root/'config.json').exists()
            print(json.dumps({'status':'passed','checks':['login','operations','describe','single-page','two-pages','auth-check','logout'],'simulated_upstream_calls':len(calls)}))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
            sock.close()


if __name__ == '__main__':
    main()
