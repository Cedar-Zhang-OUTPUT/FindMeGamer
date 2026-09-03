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

[[ ! "$base_url" =~ [[:cntrl:]] ]] || fail "base URL must be one safe HTTPS origin"
[[ "$base_url" =~ ^https://([A-Za-z0-9.-]+)(:([0-9]{1,5}))?$ ]] ||
  fail "base URL must be one safe HTTPS origin"
base_host="${BASH_REMATCH[1]}"
base_port="${BASH_REMATCH[3]}"
[[ ${#base_host} -le 253 && "$base_host" != .* && "$base_host" != *. && "$base_host" != *..* ]] ||
  fail "base URL must be one safe HTTPS origin"
IFS='.' read -r -a host_labels <<<"$base_host"
for host_label in "${host_labels[@]}"; do
  [[ ${#host_label} -ge 1 && ${#host_label} -le 63 ]] || fail "base URL must be one safe HTTPS origin"
  [[ "$host_label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] ||
    fail "base URL must be one safe HTTPS origin"
done
[[ ! "$base_host" =~ ^[0-9.]+$ ]] || fail "base URL must not use a literal IP address"
if [[ -n "$base_port" ]]; then
  base_port_value=$((10#$base_port))
  [[ "$base_port_value" -ge 1 && "$base_port_value" -le 65535 ]] ||
    fail "base URL port is invalid"
fi
base_host_lower="$(printf '%s' "$base_host" | tr '[:upper:]' '[:lower:]')"
case "$base_host_lower" in
  localhost | *.localhost | *.invalid)
    fail "base URL host is not allowed"
    ;;
  smoke.test)
    [[ "$test_mode" == "1" ]] || fail "base URL host is not allowed"
    ;;
esac

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
  jq -er '
    select(type == "object")
    | .error
    | select(type == "object")
    | select(.code | type == "string" and test("^[a-z0-9_]{1,128}$"))
    | select(.message | type == "string" and test("^[[:print:]]{1,256}$"))
    | "; \(.code): \(.message)"
  ' "$response_file" 2>/dev/null || true
}

request() {
  local endpoint_name="$1"
  local url="$2"
  local authenticated="$3"
  local expected_status="$4"
  local -a curl_arguments=(
    --disable --silent --show-error --request GET --proto '=https'
    --proto-redir '=https' --max-redirs 0 --connect-timeout 3 --max-time 10
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
  local base_filter='def safe_keys: [.. | objects | keys[] | ascii_downcase | select(contains("secret") or contains("password"))] | length == 0;'
  local shape_filter
  case "$shape" in
    health)
      shape_filter='if safe_keys and type == "object" and keys == ["status"] and .status == "ok" then "ok" else error("invalid") end'
      ;;
    session)
      shape_filter='if safe_keys and type == "object" and .api_version == "v1" and (.service_connections | type == "object") then "ok" else error("invalid") end'
      ;;
    reanalysis)
      shape_filter='if safe_keys and type == "object" and keys == ["creator_interval_days", "game_interval_days"] and ([.creator_interval_days, .game_interval_days] | all(type == "number" and floor == . and . > 0)) then "ok" else error("invalid") end'
      ;;
    connection)
      shape_filter='if safe_keys and type == "object" and keys == ["configured", "last_test_status", "last_tested_at"] and (.configured | type == "boolean") and ([null, "success", "failure"] | index($root.last_test_status) != null) and (.last_tested_at == null or (.last_tested_at | type == "string")) then (.configured | tostring) else error("invalid") end'
      ;;
    smtp)
      shape_filter='if safe_keys and type == "object" and keys == ["configured", "emails_per_minute", "encryption", "from_name", "host", "last_test_status", "last_tested_at", "port", "reply_to", "username"] and (.configured | type == "boolean") and (.emails_per_minute | type == "number" and floor == .) then (.configured | tostring) else error("invalid") end'
      ;;
    page)
      shape_filter='if safe_keys and type == "object" and keys == ["cursor", "has_more", "items"] and (.items | type == "array") and (.cursor == null or (.cursor | type == "string")) and (.has_more | type == "boolean") then (.items | length) else error("invalid") end'
      ;;
    profile-page)
      shape_filter='if safe_keys and type == "object" and keys == ["items", "next_cursor"] and (.items | type == "array") and (.next_cursor == null or (.next_cursor | type == "string")) then (.items | length) else error("invalid") end'
      ;;
    jobs)
      shape_filter='if safe_keys and type == "object" and keys == ["affected_profile_ids", "cursor", "has_more", "items"] and (.items | type == "array") and (.affected_profile_ids | type == "array") and (.cursor | type == "string" and length > 0) and (.has_more | type == "boolean") then .cursor else error("invalid") end'
      ;;
    campaign-hash)
      shape_filter='if safe_keys and type == "object" and keys == ["cursor", "has_more", "items"] and (.items | type == "array") and (.cursor == null or (.cursor | type == "string")) and (.has_more | type == "boolean") then . else error("invalid") end'
      jq -ceS "${base_filter} ${shape_filter}" "$response_file" 2>/dev/null |
        openssl dgst -sha256 2>/dev/null | awk '{print $NF}'
      return
      ;;
    *)
      return 1
      ;;
  esac
  jq -er "${base_filter} . as \$root | ${shape_filter}" "$response_file" 2>/dev/null
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
encoded_cursor="$(jq -nr --arg value "$jobs_cursor" '$value | @uri')" || fail "changed Jobs cursor could not be encoded"
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
