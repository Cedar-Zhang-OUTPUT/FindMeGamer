#!/usr/bin/env python3
"""Read-only local Match Brief viewer. No provider requests or credentials."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import secrets
from workspace import safe_id
from completion import followers_errors


def completeness(item):
    """Missing fields remain visible; never invent facts to make a row valid."""
    errors = followers_errors(item)
    presentation = item.get("presentation") or {}
    if not isinstance(presentation, dict):
        presentation = {}
    for key in ("public_name", "content_direction", "followers", "content_language", "audience_region"):
        if not isinstance(presentation.get(key), str) or not presentation[key].strip():
            errors.append("presentation." + key)
    if str(presentation.get('public_name', '')).strip().lower().startswith('unknown'):
        errors.append('presentation.public_name_needs_greeting')
    why = presentation.get("why_match") or {}
    if not isinstance(why, dict):
        why = {}
    for key in ("evidence", "gameplay_connection", "assessment", "collaboration_angle", "limitations"):
        if not isinstance(why.get(key), str) or not why[key].strip():
            errors.append("presentation.why_match." + key)
    if not str(item.get("creator", {}).get("profile_url", "")).startswith(("https://", "http://")):
        errors.append("creator.profile_url")
    contacts = item.get("contacts") or {}
    if not isinstance(contacts, dict):
        contacts = {}
    emails = contacts.get("emails")
    status = contacts.get("status")
    if not isinstance(emails, list):
        errors.append("contacts.emails")
        emails = []
    if status == "found":
        if not emails:
            errors.append("contacts.found_without_email")
        if not contacts.get('primary_email') or contacts['primary_email'] not in [
            e.get('address') for e in emails if isinstance(e, dict)
        ]:
            errors.append('contacts.primary_email')
        for email in emails:
            if not isinstance(email, dict) or any(
                not isinstance(email.get(k), str) or not email[k].strip()
                for k in ("address", "purpose", "source", "verification")
            ):
                errors.append("contacts.email_details")
    elif status == "not_found":
        if not contacts.get("lookup_completed") or emails:
            errors.append("contacts.not_found_without_completed_empty_lookup")
        for key in ('basic_lookup', 'enrichment'):
            check = contacts.get(key)
            if (not isinstance(check, dict) or check.get('status') != 'completed'
                    or not check.get('source') or key == 'enrichment' and not check.get('job_id')):
                errors.append('contacts.' + key + '_unfinished')
    elif status == "not_requested":
        if not contacts.get("reason"):
            errors.append("contacts.opt_out_reason")
    else:
        errors.append("contacts.unfinished")
    return errors


def snapshot(root, run_id):
    run = (root / "runs" / safe_id(run_id)).resolve()
    if not run.is_relative_to(root.resolve()):
        raise ValueError("Run outside workspace")
    matches, unreadable = [], 0
    for path in sorted((run / "matches").glob("*.json")):
        try:
            if not path.resolve().is_relative_to(run) or path.stat().st_size > 2_000_000:
                raise ValueError("Invalid brief")
            item = json.loads(path.read_text())
            if not isinstance(item, dict) or not isinstance(item.get("creator"), dict) or not isinstance(item.get("match"), dict):
                raise ValueError("Invalid brief")
            matches.append(item)
        except (OSError, ValueError):
            unreadable += 1
    progress = {}
    path = run / "progress.json"
    if path.exists():
        if not path.resolve().is_relative_to(run):
            raise ValueError("Progress outside workspace")
        progress = json.loads(path.read_text())
    issues = [{"account_id": m["creator"].get("account_id"), "missing": completeness(m)} for m in matches]
    return {"run_id": run_id, "matches": matches, "phase": progress.get("phase", "Research in progress"), "unreadable": unreadable,
            "incomplete": [issue for issue in issues if issue["missing"]]}


def serve(root, run_id, port=0):
    root = Path(root).resolve()
    safe_id(run_id)
    if not (root / "runs" / run_id).is_dir():
        raise ValueError("Run does not exist")
    secret = secrets.token_urlsafe(24)
    page = Path(__file__).with_name("research_dashboard.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            origin = f"http://127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != origin.removeprefix("http://") or self.headers.get("Origin") not in (None, origin):
                self.send_error(403)
                return
            status = 200
            if self.path == f"/{secret}/":
                body, kind = page, "text/html; charset=utf-8"
            elif self.path == f"/{secret}/data":
                try:
                    body = json.dumps(snapshot(root, run_id)).encode()
                except (OSError, ValueError, TypeError, AttributeError):
                    body, status = b'{"error":"Could not read research files"}', 503
                kind = "application/json"
            else:
                self.send_error(404)
                return
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(json.dumps({"url": f"http://127.0.0.1:{server.server_port}/{secret}/", "read_only": True}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    if args.validate:
        result = snapshot(args.root, args.run_id)
        print(json.dumps({"incomplete": result["incomplete"], "unreadable": result["unreadable"]}))
        raise SystemExit(2 if result["incomplete"] or result["unreadable"] else 0)
    else:
        serve(args.root, args.run_id, args.port)
