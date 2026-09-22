#!/usr/bin/env python3
"""Local game/filter approval. No provider calls, credentials or automatic searches."""
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import time
from review_filters import validate, LANGUAGES, REGIONS, PRESETS
from workspace import atomic, safe_id, lock


def paths(root, run_id):
    root = Path(root).resolve()
    run = (root / 'runs' / safe_id(run_id)).resolve()
    if not run.is_relative_to(root) or not run.is_dir():
        raise ValueError('Invalid run directory')
    return root, run


def read(path, root):
    if not path.resolve().is_relative_to(root) or path.stat().st_size > 2_000_000:
        raise ValueError('Invalid local input')
    return path.read_text()


def proposal(root, run_id):
    root, run = paths(root, run_id)
    profile = read(root / 'game-profile.md', root)
    intent = read(run / 'search-intent.json', run)
    data = json.loads(intent)
    filters = validate(data.get('filters', {}))
    revision = hashlib.sha256(json.dumps([profile, intent]).encode()).hexdigest()
    corrections = ''
    saved_path = run / 'game-confirmation.json'
    if saved_path.exists():
        saved = json.loads(read(saved_path, run))
        if saved.get('status') == 'approved' and saved.get('revision') == revision:
            filters = validate(saved['filters'])
            corrections = saved.get('corrections', '')
    return {'revision': revision, 'profile': profile, 'search_intent': data,
            'filters': filters, 'corrections': corrections,
            'languages': LANGUAGES, 'regions': REGIONS, 'presets': PRESETS}


def confirmation(root, run_id):
    root, run = paths(root, run_id)
    path = run / 'game-confirmation.json'
    if not path.exists():
        return None
    record = json.loads(read(path, run))
    if record.get('status') == 'approved' and record.get('revision') == proposal(root, run_id)['revision']:
        return record
    return None


def save(root, run_id, data):
    root, run = paths(root, run_id)
    with lock(root):
        current = proposal(root, run_id)
        if data.get('revision') != current['revision']:
            raise ValueError('Game or search plan changed; reload and review again')
        filters = validate(data.get('filters'))
        if filters['regions']['pending']:
            raise ValueError('Unconfirmed region labels: ask the Agent to resolve these before approval')
        corrections = data.get('corrections', '')
        if not isinstance(corrections, str) or len(corrections) > 10000:
            raise ValueError('Corrections must be text up to 10000 characters')
        record = {'status': 'approved', 'source': 'local_browser_user_save',
                  'revision': current['revision'], 'profile_snapshot': current['profile'],
                  'search_intent_snapshot': current['search_intent'], 'filters': filters,
                  'corrections': corrections, 'approved_at': datetime.now(timezone.utc).isoformat()}
        atomic(run / 'game-confirmation.json', record)
        return record


def server(root, run_id, port=0):
    proposal(root, run_id)
    secret = secrets.token_urlsafe(24)
    page = Path(__file__).with_suffix('.html').read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def allowed(self, write=False):
            origin = f'http://127.0.0.1:{self.server.server_port}'
            return (self.headers.get('Host') == origin[7:] and
                    self.headers.get('Origin') in ((origin,) if write else (None, origin)))

        def reply(self, data, code=200, html=False):
            self.send_response(code)
            self.send_header('Content-Type', 'text/html; charset=utf-8' if html else 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data if html else json.dumps(data).encode())

        def do_GET(self):
            if not self.allowed():
                return self.reply({'error': 'Forbidden'}, 403)
            if self.path == f'/{secret}/':
                return self.reply(page, html=True)
            if self.path == f'/{secret}/data':
                try:
                    return self.reply(proposal(root, run_id))
                except (OSError, ValueError, TypeError, AttributeError):
                    return self.reply({'error': 'Cannot read game or search plan'}, 400)
            self.reply({'error': 'Not found'}, 404)

        def do_POST(self):
            if not self.allowed(write=True):
                return self.reply({'error': 'Forbidden'}, 403)
            if self.path != f'/{secret}/save':
                return self.reply({'error': 'Not found'}, 404)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536 or self.headers.get('Content-Type') != 'application/json':
                    raise ValueError('Expected bounded JSON request')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError('Invalid request')
                self.reply(save(root, run_id, payload))
            except (ValueError, TypeError, KeyError, OSError) as error:
                self.reply({'error': str(error)}, 400)

    result = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    result.timeout = 1
    return result, f'http://127.0.0.1:{result.server_port}/{secret}/'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['serve', 'wait', 'status'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--timeout', type=float, default=45)
    args = parser.parse_args()
    if args.action == 'serve':
        http, url = server(args.root, args.run_id)
        print(json.dumps({'url': url, 'purpose': 'game_filter_confirmation'}), flush=True)
        try:
            http.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            http.server_close()
    else:
        deadline = time.monotonic() + (min(max(args.timeout, 0), 55) if args.action == 'wait' else 0)
        while True:
            result = confirmation(args.root, args.run_id)
            if result is not None or time.monotonic() >= deadline:
                print(json.dumps(result or {'status': 'awaiting_confirmation'}))
                break
            time.sleep(.25)
