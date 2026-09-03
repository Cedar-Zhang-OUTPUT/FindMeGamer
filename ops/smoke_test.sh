#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "smoke: $*" >&2
  exit 1
}

file_mode() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    stat -f '%Lp' "$1"
  else
    stat -c '%a' "$1"
  fi
}

file_owner_id() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    stat -f '%u' "$1"
  else
    stat -c '%u' "$1"
  fi
}

[[ $# -eq 1 ]] || fail "usage: FMG_WORKSPACE_KEY_FILE=<absolute-path> $0 <https-base-url>"
base_url="$1"
test_mode="${FMG_OPERATOR_TEST_MODE:-0}"
[[ "$test_mode" == "0" || "$test_mode" == "1" ]] || fail "test mode must be 0 or 1"

curl_bin="curl"
if [[ "$test_mode" == "1" ]]; then
  curl_bin="${FMG_CURL_BIN:?FMG_CURL_BIN is required in test mode}"
elif [[ -n "${FMG_CURL_BIN:-}" ]]; then
  fail "curl override is allowed only in test mode"
fi

python3 - "$base_url" "$test_mode" 2>/dev/null <<'PY' || fail "base URL must be one safe HTTPS origin"
import ipaddress
import socket
import sys
from urllib.parse import urlsplit

raw, test_mode = sys.argv[1:]
if any(ord(character) < 32 or ord(character) == 127 for character in raw):
    raise SystemExit(1)
parsed = urlsplit(raw)
if (
    parsed.scheme != "https"
    or not parsed.hostname
    or parsed.username is not None
    or parsed.password is not None
    or parsed.path
    or parsed.query
    or parsed.fragment
):
    raise SystemExit(1)
try:
    parsed.port
except ValueError:
    raise SystemExit(1)
host = parsed.hostname.rstrip(".").casefold()
if host == "localhost" or host.endswith(".localhost") or host.endswith(".invalid"):
    if not (test_mode == "1" and host == "smoke.test"):
        raise SystemExit(1)
if test_mode == "0":
    addresses = {entry[4][0] for entry in socket.getaddrinfo(host, parsed.port or 443)}
    for address in addresses:
        value = ipaddress.ip_address(address)
        if value.is_loopback or value.is_unspecified or value.is_link_local:
            raise SystemExit(1)
PY

key_file="${FMG_WORKSPACE_KEY_FILE:-}"
[[ "$key_file" == /* ]] || fail "Workspace key file must be an absolute path"
[[ -f "$key_file" && ! -L "$key_file" ]] || fail "Workspace key file must be a regular non-symlink file"
[[ "$(file_mode "$key_file")" == "600" ]] || fail "Workspace key file must have mode 0600"
key_owner="$(file_owner_id "$key_file")"
operator_id="$(id -u)"
[[ "$key_owner" == "0" || "$key_owner" == "$operator_id" ]] || fail "Workspace key file has an invalid owner"

workspace_key=""
key_lines=0
while IFS= read -r key_line || [[ -n "$key_line" ]]; do
  key_lines=$((key_lines + 1))
  [[ "$key_lines" -le 1 ]] || fail "Workspace key file must contain exactly one line"
  workspace_key="$key_line"
done <"$key_file"
[[ "$key_lines" -eq 1 && -n "$workspace_key" && ${#workspace_key} -le 512 ]] || fail "Workspace key file is empty or too long"
[[ "$workspace_key" =~ ^[A-Za-z0-9._~+/=-]+$ ]] || fail "Workspace key contains unsafe header characters"

umask 077
temporary_dir="$(mktemp -d "${TMPDIR:-/tmp}/fmg-smoke.XXXXXX")"
header_file="${temporary_dir}/authorization.conf"
response_file="${temporary_dir}/response.body"
cleanup() {
  unset workspace_key key_line
  rm -f "$header_file" "$response_file"
  rmdir "$temporary_dir" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT TERM
printf 'header = "Authorization: Bearer %s"\n' "$workspace_key" >"$header_file"
chmod 600 "$header_file"
: >"$response_file"
chmod 600 "$response_file"
unset workspace_key key_line

safe_error_suffix() {
  python3 - "$response_file" <<'PY'
import json
from pathlib import Path
import re
import sys

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if (
        isinstance(code, str)
        and isinstance(message, str)
        and re.fullmatch(r"[a-z0-9_]{1,128}", code)
        and 1 <= len(message) <= 256
        and all(character.isprintable() for character in message)
    ):
        print(f"; {code}: {message}", end="")
except Exception:
    pass
PY
}

request() {
  local endpoint_name="$1"
  local url="$2"
  local authenticated="$3"
  local expected_status="$4"
  local -a curl_arguments=(
    --silent --show-error --connect-timeout 3 --max-time 10
    --output "$response_file" --write-out '%{http_code}'
  )
  if [[ "$authenticated" == "yes" ]]; then
    curl_arguments+=(--config "$header_file")
  fi
  http_status="$("$curl_bin" "${curl_arguments[@]}" "$url" 2>/dev/null)" || fail "$endpoint_name request failed"
  [[ "$http_status" =~ ^[0-9]{3}$ ]] || fail "$endpoint_name returned an invalid HTTP status"
  if [[ "$http_status" != "$expected_status" ]]; then
    suffix="$(safe_error_suffix)"
    fail "$endpoint_name failed (HTTP ${http_status}${suffix})"
  fi
}

validate_json() {
  local shape="$1"
  python3 - "$response_file" "$shape" 2>/dev/null <<'PY'
import hashlib
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
shape = sys.argv[2]

def no_secrets(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            assert "secret" not in key.casefold() and "password" not in key.casefold()
            no_secrets(nested)
    elif isinstance(value, list):
        for nested in value:
            no_secrets(nested)

no_secrets(payload)
if shape == "health":
    assert payload == {"status": "ok"}
    print("ok")
elif shape == "session":
    assert isinstance(payload, dict) and payload.get("api_version") == "v1"
    assert isinstance(payload.get("service_connections"), dict)
    print("ok")
elif shape == "reanalysis":
    assert set(payload) == {"creator_interval_days", "game_interval_days"}
    assert all(isinstance(payload[key], int) and payload[key] > 0 for key in payload)
    print("ok")
elif shape == "connection":
    assert set(payload) == {"configured", "last_test_status", "last_tested_at"}
    assert isinstance(payload["configured"], bool)
    assert payload["last_test_status"] in (None, "success", "failure")
    assert payload["last_tested_at"] is None or isinstance(payload["last_tested_at"], str)
    print(str(payload["configured"]).lower())
elif shape == "smtp":
    expected = {"configured", "host", "port", "encryption", "username", "from_name", "reply_to", "emails_per_minute", "last_test_status", "last_tested_at"}
    assert set(payload) == expected and isinstance(payload["configured"], bool)
    assert isinstance(payload["emails_per_minute"], int)
    print(str(payload["configured"]).lower())
elif shape == "page":
    assert set(payload) == {"items", "cursor", "has_more"}
    assert isinstance(payload["items"], list)
    assert payload["cursor"] is None or isinstance(payload["cursor"], str)
    assert isinstance(payload["has_more"], bool)
    print(len(payload["items"]))
elif shape == "profile-page":
    assert set(payload) == {"items", "next_cursor"}
    assert isinstance(payload["items"], list)
    assert payload["next_cursor"] is None or isinstance(payload["next_cursor"], str)
    print(len(payload["items"]))
elif shape == "jobs":
    assert set(payload) == {"items", "cursor", "has_more", "affected_profile_ids"}
    assert isinstance(payload["items"], list) and isinstance(payload["affected_profile_ids"], list)
    assert isinstance(payload["cursor"], str) and payload["cursor"]
    assert isinstance(payload["has_more"], bool)
    print(payload["cursor"])
elif shape == "campaign-hash":
    assert set(payload) == {"items", "cursor", "has_more"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    print(hashlib.sha256(canonical).hexdigest())
else:
    raise AssertionError("unknown expected shape")
PY
}

request "health/live" "${base_url}/health/live" no 200
[[ "$(validate_json health)" == "ok" ]] || fail "health/live payload is invalid"
echo "PASS health/live"
request "health/ready" "${base_url}/health/ready" no 200
[[ "$(validate_json health)" == "ok" ]] || fail "health/ready payload is invalid"
echo "PASS health/ready"
request "session" "${base_url}/api/v1/session" yes 200
[[ "$(validate_json session)" == "ok" ]] || fail "session payload is invalid"
echo "PASS session"
request "re-analysis settings" "${base_url}/api/v1/settings/reanalysis" yes 200
[[ "$(validate_json reanalysis)" == "ok" ]] || fail "re-analysis settings payload is invalid"
echo "PASS re-analysis settings"
for service in steam youtube deepseek; do
  request "${service} connection" "${base_url}/api/v1/settings/connections/${service}" yes 200
  configured="$(validate_json connection)" || fail "${service} connection payload is invalid"
  echo "PASS ${service} configured=${configured}"
done
request "SMTP status" "${base_url}/api/v1/outreach/smtp" yes 200
smtp_configured="$(validate_json smtp)" || fail "SMTP status payload is invalid"
echo "PASS smtp configured=${smtp_configured}"
for profile_type in games creators; do
  request "${profile_type} Library" "${base_url}/api/v1/profiles/${profile_type}" yes 200
  item_count="$(validate_json profile-page)" || fail "${profile_type} Library payload is invalid"
  echo "PASS ${profile_type} count=${item_count}"
done
request "changed Jobs" "${base_url}/api/v1/jobs" yes 200
jobs_cursor="$(validate_json jobs)" || fail "changed Jobs payload is invalid"
encoded_cursor="$(python3 - "$jobs_cursor" <<'PY'
import sys
from urllib.parse import quote
print(quote(sys.argv[1], safe=""))
PY
)"
request "changed Jobs cursor" "${base_url}/api/v1/jobs?changed_after=${encoded_cursor}" yes 200
validate_json jobs >/dev/null || fail "changed Jobs cursor payload is invalid"
echo "PASS changed Jobs cursor"
request "Match history" "${base_url}/api/v1/matches" yes 200
match_count="$(validate_json page)" || fail "Match history payload is invalid"
echo "PASS matches count=${match_count}"
request "Outreach campaigns" "${base_url}/api/v1/outreach/campaigns" yes 200
campaign_before="$(validate_json campaign-hash)" || fail "campaign payload is invalid"
request "invalid response capability" "${base_url}/r/not-a-capability?choice=accepted" no 404
grep -Fq "Response link not found" "$response_file" || fail "invalid response capability page is invalid"
request "Outreach campaigns after public GET" "${base_url}/api/v1/outreach/campaigns" yes 200
campaign_after="$(validate_json campaign-hash)" || fail "campaign payload is invalid after public GET"
[[ "$campaign_after" == "$campaign_before" ]] || fail "public response GET changed campaign state"
echo "PASS public response GET read-only"
