#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "release evidence: $*" >&2
  exit 1
}

[[ $# -eq 1 ]] || fail "usage: $0 <x.y.z>"
version="$1"
[[ "$version" =~ ^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] ||
  fail "version must be an exact three-component semantic version"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
repository_root="$(cd "$script_dir/.." && pwd -P)"
[[ -f "$repository_root/docs/release-checklist.md" && -f "$repository_root/compose.yaml" ]] ||
  fail "repository root is invalid"

dry_run="${FMG_DRY_RUN:-0}"
test_mode="${FMG_RELEASE_EVIDENCE_TEST_MODE:-0}"
[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "FMG_DRY_RUN must be 0 or 1"
[[ "$test_mode" == "0" || "$test_mode" == "1" ]] || fail "evidence test mode must be 0 or 1"

evidence_relative="release/evidence/${version}"
evidence_names=(
  deployed-commit.txt
  compose-services.json
  alembic-revision.txt
  health-live.json
  health-ready.json
  release-artifact.txt
  release-verification.json
  restore-summary.json
  release-checklist.md
)

if [[ "$dry_run" == "1" ]]; then
  for evidence_name in "${evidence_names[@]}"; do
    printf '%s/%s\n' "$evidence_relative" "$evidence_name"
  done
  echo "PLAN: read-only deployed commit, Compose status, migration revision, public health, release trust, restore summary, and checklist snapshot"
  echo "PASS"
  exit 0
fi

temporary_dir=""
cleanup() {
  cleanup_status=$?
  trap - EXIT INT TERM
  if [[ -n "$temporary_dir" && -d "$temporary_dir" && ! -L "$temporary_dir" &&
    "$temporary_dir" == "$repository_root/release/evidence/.tmp-${version}."* ]]; then
    rm -rf -- "$temporary_dir"
  fi
  exit "$cleanup_status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

sensitive_environment_names=(
  WORKSPACE_ACCESS_KEY FMG_WORKSPACE_ACCESS_KEY FMG_WORKSPACE_KEY
  WORKSPACE_KEY FMG_WORKSPACE_KEY_FILE API_KEY OPENAI_API_KEY STEAM_API_KEY
  YOUTUBE_API_KEY DEEPSEEK_API_KEY SMTP_PASSWORD SMTP_USERNAME
  NETEASE_PASSWORD FMG_MASTER_KEY MASTER_KEY MASTER_KEY_FILE RESPONSE_TOKEN
  RESPONSE_CAPABILITY RECIPIENT_EMAIL EMAIL AWS_ACCESS_KEY_ID
  AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN DATABASE_URL
)
for sensitive_name in "${sensitive_environment_names[@]}"; do
  [[ -z "${!sensitive_name-}" ]] || fail "sensitive credential environment input is not accepted"
done

if [[ "$test_mode" == "1" ]]; then
  ssh_bin="${FMG_SSH_BIN:?FMG_SSH_BIN is required in test mode}"
  curl_bin="${FMG_CURL_BIN:?FMG_CURL_BIN is required in test mode}"
  verify_release_bin="${FMG_VERIFY_RELEASE_BIN:?FMG_VERIFY_RELEASE_BIN is required in test mode}"
  command_timeout="${FMG_EVIDENCE_COMMAND_TIMEOUT_SECONDS:-2}"
  [[ "$command_timeout" =~ ^[1-9][0-9]?$ ]] || fail "test command timeout is invalid"
else
  [[ -z "${FMG_SSH_BIN:-}${FMG_CURL_BIN:-}${FMG_DOCKER_BIN:-}${FMG_VERIFY_RELEASE_BIN:-}${FMG_EVIDENCE_COMMAND_TIMEOUT_SECONDS:-}" ]] ||
    fail "command overrides are allowed only in test mode"
  ssh_bin="/usr/bin/ssh"
  curl_bin="/usr/bin/curl"
  verify_release_bin="$repository_root/script/verify_release.sh"
  command_timeout=30
fi
[[ -x "$ssh_bin" && -x "$curl_bin" && -x "$verify_release_bin" ]] ||
  fail "required read-only command is unavailable"

validate_https_origin() {
  local value="$1"
  local host port host_lower port_value label
  local -a labels
  [[ ! "$value" =~ [[:cntrl:]] ]] || return 1
  [[ "$value" =~ ^https://([A-Za-z0-9.-]+)(:([0-9]{1,5}))?$ ]] || return 1
  host="${BASH_REMATCH[1]}"
  port="${BASH_REMATCH[3]}"
  [[ ${#host} -le 253 && "$host" != .* && "$host" != *. && "$host" != *..* ]] || return 1
  IFS='.' read -r -a labels <<<"$host"
  for label in "${labels[@]}"; do
    [[ ${#label} -ge 1 && ${#label} -le 63 ]] || return 1
    [[ "$label" =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || return 1
  done
  [[ ! "$host" =~ ^[0-9.]+$ ]] || return 1
  if [[ -n "$port" ]]; then
    port_value=$((10#$port))
    [[ "$port_value" -ge 1 && "$port_value" -le 65535 ]] || return 1
  fi
  host_lower="$(printf '%s' "$host" | tr '[:upper:]' '[:lower:]')"
  case "$host_lower" in
    localhost | *.localhost | *.invalid)
      return 1
      ;;
    release.test)
      [[ "$test_mode" == "1" ]] || return 1
      ;;
  esac
}

validate_ssh_destination() {
  local value="$1"
  local hostname host_lower
  [[ ! "$value" =~ [[:cntrl:]] ]] || return 1
  [[ "$value" =~ ^([A-Za-z][A-Za-z0-9._-]{0,31}@)?([A-Za-z0-9][A-Za-z0-9.-]{0,252})$ ]] || return 1
  hostname="${BASH_REMATCH[2]}"
  [[ "$hostname" != .* && "$hostname" != *. && "$hostname" != *..* && "$hostname" != *.-* && "$hostname" != *-.* ]] || return 1
  [[ ! "$hostname" =~ ^[0-9.]+$ ]] || return 1
  host_lower="$(printf '%s' "$hostname" | tr '[:upper:]' '[:lower:]')"
  case "$host_lower" in
    localhost | *.localhost | *.invalid)
      return 1
      ;;
    evidence.test)
      [[ "$test_mode" == "1" ]] || return 1
      ;;
  esac
}

ec2_host="${FMG_EC2_HOST:-}"
service_origin="${SERVICE_BASE_URL:-}"
restore_input="${FMG_RESTORE_RESULT_FILE:-}"
validate_ssh_destination "$ec2_host" || fail "SSH destination is invalid"
validate_https_origin "$service_origin" || fail "service HTTPS origin is invalid"

release_dir="$repository_root/release"
archive="$release_dir/FindMeGamer-${version}.zip"
sidecar="${archive}.sha256"
restore_expected="$release_dir/restore-result-${version}.txt"
checklist="$repository_root/docs/release-checklist.md"
evidence_root="$release_dir/evidence"
destination="$evidence_root/$version"

[[ -d "$release_dir" && ! -L "$release_dir" ]] || fail "release input directory is invalid"
[[ -f "$archive" && ! -L "$archive" ]] || fail "release archive is missing or unsafe"
[[ -f "$sidecar" && ! -L "$sidecar" ]] || fail "release checksum is missing or unsafe"
[[ -f "$checklist" && ! -L "$checklist" ]] || fail "release checklist is missing or unsafe"
restore_parent="$(cd "$(dirname "$restore_input")" 2>/dev/null && pwd -P)" ||
  fail "restore result parent is invalid"
restore_canonical="$restore_parent/$(basename "$restore_input")"
[[ "$restore_canonical" == "$restore_expected" && -f "$restore_input" && ! -L "$restore_input" ]] ||
  fail "restore result path is outside the exact release input location or unsafe"
[[ ! -e "$destination" && ! -L "$destination" ]] || fail "evidence destination already exists"
if [[ -e "$evidence_root" ]]; then
  [[ -d "$evidence_root" && ! -L "$evidence_root" ]] || fail "evidence root is unsafe"
fi

sha256_file() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    return 1
  fi
}

[[ "$(wc -l <"$sidecar" | tr -d ' ')" == "1" ]] || fail "release checksum sidecar is malformed"
IFS=' ' read -r expected_digest expected_basename unexpected_sidecar <"$sidecar" ||
  fail "release checksum sidecar is unreadable"
[[ "$expected_digest" =~ ^[0-9a-f]{64}$ && "$expected_basename" == "$(basename "$archive")" && -z "$unexpected_sidecar" ]] ||
  fail "release checksum sidecar is malformed"
actual_digest="$(sha256_file "$archive")" || fail "release checksum cannot be computed"
[[ "$actual_digest" == "$expected_digest" ]] || fail "release checksum mismatch"

header_value() {
  local field="$1"
  awk -v prefix="- ${field}:" '
    index($0, prefix) == 1 {
      count += 1
      value = substr($0, length(prefix) + 1)
      sub(/^[[:space:]]+/, "", value)
      print value
    }
    END { if (count != 1) exit 1 }
  ' "$checklist"
}

release_version="$(header_value "Release version")" || fail "checklist release version field is invalid"
deployed_commit="$(header_value "Immutable deployed commit")" || fail "checklist deployed commit field is invalid"
checklist_origin="$(header_value "Service HTTPS origin")" || fail "checklist service origin field is invalid"
checklist_archive="$(header_value "Release artifact")" || fail "checklist artifact field is invalid"
checklist_digest="$(header_value "Release checksum")" || fail "checklist checksum field is invalid"
environment_label="$(header_value "EC2 environment label")" || fail "checklist environment field is invalid"
utc_start="$(header_value "UTC start time")" || fail "checklist start time field is invalid"
utc_completion="$(header_value "UTC completion time")" || fail "checklist completion time field is invalid"
primary_operator="$(header_value "Primary operator")" || fail "checklist operator field is invalid"
witness="$(header_value "Independent witness")" || fail "checklist witness field is invalid"
decision="$(header_value "Final release decision")" || fail "checklist decision field is invalid"

[[ "$release_version" == "$version" ]] || fail "checklist release version does not match"
[[ "$deployed_commit" =~ ^[0-9a-f]{40}$ ]] || fail "checklist deployed commit is invalid"
[[ "$checklist_origin" == "$service_origin" ]] || fail "checklist service origin does not match"
[[ "$checklist_archive" == "release/$(basename "$archive")" ]] || fail "checklist artifact does not match"
[[ "$checklist_digest" == "$actual_digest" ]] || fail "checklist checksum does not match"
[[ "$environment_label" =~ ^[A-Za-z0-9][-A-Za-z0-9._\ ]{0,79}$ ]] || fail "checklist environment label is invalid"
[[ "$utc_start" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ &&
  "$utc_completion" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$ ]] ||
  fail "checklist UTC times are invalid"
[[ -n "$primary_operator" && "$primary_operator" != *___* && ${#primary_operator} -le 80 ]] || fail "checklist primary operator is invalid"
[[ -n "$witness" && "$witness" != *___* && ${#witness} -le 80 ]] || fail "checklist witness is invalid"
[[ "$decision" == "PASS" ]] || fail "checklist final decision is incomplete"

if LC_ALL=C grep -Eq '[[:cntrl:]]|SECRET-CANARY|BEGIN ([A-Z ]+)?PRIVATE KEY|Authorization[[:space:]]*:|Cookie[[:space:]]*:|(^|[^A-Za-z])(password|secret|token|database_url)[[:space:]]*=' "$checklist"; then
  fail "checklist contains prohibited sensitive content"
fi
if grep -Eiq '^- (workspace|api|provider|steam|youtube|deepseek|smtp|master|response|aws).*(key|token|password|secret|credential)[[:space:]]*:' "$checklist"; then
  fail "checklist contains a prohibited credential field"
fi
if grep -Eq '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$checklist"; then
  fail "checklist contains an email address"
fi

awk '
  BEGIN {
    split("workspace-key steam-analyze youtube-analyze library reanalyze creator-seed three-stage-match outreach accepted declined duplicate-send cloud-continuation offline-reconnect macos-14 macos-26 backup-restore master-key-recovery", expected, " ")
    split("Responsible operator|UTC timestamp|Environment/device/OS|Prerequisites/test data|Steps|Expected outcome|Actual outcome|Evidence filenames", fields, "|")
  }
  /^## Scenario: / {
    scenario += 1
    current = substr($0, length("## Scenario: ") + 1)
    if (scenario > 17 || current != expected[scenario]) exit 20
    next
  }
  scenario > 0 && /^- id: / {
    value = substr($0, length("- id: ") + 1)
    if (value != current) exit 21
    ids[current] += 1
    next
  }
  scenario > 0 {
    for (field_index = 1; field_index <= 8; field_index += 1) {
      prefix = "- " fields[field_index] ":"
      if (index($0, prefix) == 1) {
        key = current SUBSEP fields[field_index]
        seen[key] += 1
        value = substr($0, length(prefix) + 1)
        sub(/^[[:space:]]+/, "", value)
        if (value == "" || value ~ /___/) exit 22
        if (fields[field_index] == "Evidence filenames" && value !~ /^[A-Za-z0-9._-]+(, [A-Za-z0-9._-]+)*$/) exit 23
        if (fields[field_index] == "Actual outcome" && tolower(value) ~ /(authorization|cookie|workspace key|api key|password|secret|response token|mail body|database_url)/) exit 28
      }
    }
  }
  scenario > 0 && $0 == "- [x] PASS" { passed[current] += 1; next }
  scenario > 0 && $0 == "- [ ] FAIL" { failed[current] += 1; next }
  scenario > 0 && ($0 == "- [ ] PASS" || $0 == "- [x] FAIL" || $0 == "- [X] PASS" || $0 == "- [X] FAIL") { exit 24 }
  END {
    if (scenario != 17) exit 25
    for (scenario_index = 1; scenario_index <= 17; scenario_index += 1) {
      id = expected[scenario_index]
      if (ids[id] != 1 || passed[id] != 1 || failed[id] != 1) exit 26
      for (field_index = 1; field_index <= 8; field_index += 1) {
        if (seen[id SUBSEP fields[field_index]] != 1) exit 27
      }
    }
  }
' "$checklist" || fail "checklist scenarios are incomplete or malformed"

grep -Eq '^- \[x\] Primary operator approval — name / UTC: .+ / [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "$checklist" ||
  fail "primary operator sign-off is incomplete"
grep -Eq '^- \[x\] Independent witness approval — name / UTC: .+ / [0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$' "$checklist" ||
  fail "independent witness sign-off is incomplete"

[[ "$(wc -l <"$restore_input" | tr -d ' ')" == "3" ]] || fail "restore result schema is invalid"
restore_result="$(sed -n '1s/^result=//p' "$restore_input")"
restore_revision="$(sed -n '2s/^alembic_revision=//p' "$restore_input")"
restore_table_count="$(sed -n '3s/^required_table_count=//p' "$restore_input")"
[[ "$restore_result" == "PASS" && "$restore_revision" =~ ^[A-Za-z0-9_]+$ && "$restore_table_count" == "6" ]] ||
  fail "restore result schema is invalid"
[[ "$(sed -n '1p' "$restore_input")" == "result=PASS" &&
  "$(sed -n '2p' "$restore_input")" == "alembic_revision=${restore_revision}" &&
  "$(sed -n '3p' "$restore_input")" == "required_table_count=6" ]] ||
  fail "restore result schema is invalid"

umask 077
mkdir -p "$evidence_root"
[[ -d "$evidence_root" && ! -L "$evidence_root" ]] || fail "evidence root could not be created safely"
temporary_dir="$(mktemp -d "$evidence_root/.tmp-${version}.XXXXXX")" || fail "private evidence directory could not be created"
[[ -d "$temporary_dir" && ! -L "$temporary_dir" && "$temporary_dir" == "$evidence_root/.tmp-${version}."* ]] ||
  fail "private evidence directory is unsafe"
chmod 0700 "$temporary_dir"

run_bounded() {
  local output="$1"
  local command_pid watchdog_pid command_status
  shift
  "$@" >"$output" 2>/dev/null &
  command_pid=$!
  (
    sleep "$command_timeout"
    : >"${output}.timeout"
    kill -TERM "$command_pid" 2>/dev/null || exit 0
    sleep 1
    kill -KILL "$command_pid" 2>/dev/null || true
  ) &
  watchdog_pid=$!
  if wait "$command_pid"; then
    command_status=0
  else
    command_status=$?
  fi
  kill "$watchdog_pid" 2>/dev/null || true
  wait "$watchdog_pid" 2>/dev/null || true
  if [[ -e "${output}.timeout" ]]; then
    return 124
  fi
  return "$command_status"
}

capture_or_fail() {
  local stage="$1"
  local output="$2"
  local capture_status
  shift 2
  if run_bounded "$output" "$@"; then
    return 0
  else
    capture_status=$?
  fi
  if [[ "$capture_status" == "124" ]]; then
    fail "$stage timed out"
  fi
  fail "$stage capture failed"
}

ssh_options=(-o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=5 -o ServerAliveCountMax=2)
remote_prefix="cd /opt/find-me-gamer &&"
raw_commit="$temporary_dir/.deployed-commit.raw"
capture_or_fail "deployed commit" "$raw_commit" "$ssh_bin" "${ssh_options[@]}" "$ec2_host" \
  "$remote_prefix git rev-parse HEAD"
[[ "$(wc -l <"$raw_commit" | tr -d ' ')" == "1" ]] || fail "deployed commit output is malformed"
captured_commit="$(tr -d '\r\n' <"$raw_commit")"
[[ "$captured_commit" =~ ^[0-9a-f]{40}$ && "$captured_commit" == "$deployed_commit" ]] ||
  fail "deployed commit does not match the completed checklist"
printf '%s\n' "$captured_commit" >"$temporary_dir/deployed-commit.txt"

raw_compose="$temporary_dir/.compose.raw"
capture_or_fail "Compose status" "$raw_compose" "$ssh_bin" "${ssh_options[@]}" "$ec2_host" \
  "$remote_prefix sudo docker compose --env-file /etc/find-me-gamer/app.env --project-directory /opt/find-me-gamer ps --format json proxy api worker beat postgres redis"
jq -ecs '
  if length == 1 and (.[0] | type) == "array" then .[0] else . end
  | if ([.. | objects | keys[] | ascii_downcase | select(test("authorization|cookie|key|token|password|secret|database_url|email|body"))] | length) == 0 then . else error("sensitive") end
  | map({service: .Service, state: .State, health: .Health})
  | sort_by(.service)
  | select(map(.service) == ["api", "beat", "postgres", "proxy", "redis", "worker"])
  | select(all(.[]; (.state == "running") and (.health == "healthy")))
' "$raw_compose" >"$temporary_dir/compose-services.json" 2>/dev/null || fail "Compose status output is malformed or unhealthy"

raw_revision="$temporary_dir/.alembic.raw"
capture_or_fail "Alembic revision" "$raw_revision" "$ssh_bin" "${ssh_options[@]}" "$ec2_host" \
  "$remote_prefix sudo docker compose --env-file /etc/find-me-gamer/app.env --project-directory /opt/find-me-gamer exec -T api alembic current"
[[ "$(wc -l <"$raw_revision" | tr -d ' ')" == "1" ]] || fail "Alembic revision output is malformed"
revision_line="$(tr -d '\r\n' <"$raw_revision")"
[[ "$revision_line" =~ ^([A-Za-z0-9_]+)[[:space:]]+\(head\)$ ]] || fail "Alembic revision output is malformed"
captured_revision="${BASH_REMATCH[1]}"
[[ "$captured_revision" == "$restore_revision" ]] || fail "Alembic revision does not match restore evidence"
printf '%s\n' "$captured_revision" >"$temporary_dir/alembic-revision.txt"

capture_health() {
  local endpoint="$1"
  local filename="$2"
  local raw_body="$temporary_dir/.${filename}.raw"
  local raw_status="$temporary_dir/.${filename}.status"
  capture_or_fail "${endpoint} health" "$raw_status" "$curl_bin" --disable --silent --show-error \
    --request GET --proto '=https' --proto-redir '=https' --max-redirs 0 --noproxy '*' \
    --connect-timeout 5 --max-time 15 --output "$raw_body" --write-out '%{http_code}' \
    "${service_origin}/health/${endpoint}"
  [[ "$(tr -d '\r\n' <"$raw_status")" == "200" ]] || fail "${endpoint} health returned a non-success status"
  jq -ecS 'select(type == "object" and keys == ["status"] and .status == "ok") | {status: .status}' \
    "$raw_body" >"$temporary_dir/$filename" 2>/dev/null || fail "${endpoint} health output is malformed"
}
capture_health live health-live.json
capture_health ready health-ready.json

raw_verification="$temporary_dir/.release-verification.raw"
capture_or_fail "release verification" "$raw_verification" "$verify_release_bin" "$archive"
[[ "$(wc -l <"$raw_verification" | tr -d ' ')" == "3" &&
  "$(sed -n '1p' "$raw_verification")" == "PASS checksum" &&
  "$(sed -n '2p' "$raw_verification")" == "PASS Developer ID, Gatekeeper, and stapled ticket verification" &&
  "$(sed -n '3p' "$raw_verification")" == "Verified: $archive" ]] ||
  fail "release verification output is malformed"
printf '{"checksum":true,"codesign":true,"gatekeeper":true,"stapled_ticket":true}\n' >"$temporary_dir/release-verification.json"

printf 'archive=%s\nsha256=%s\n' "$(basename "$archive")" "$actual_digest" >"$temporary_dir/release-artifact.txt"
printf '{"alembic_revision":"%s","required_table_count":6,"result":"PASS"}\n' "$restore_revision" >"$temporary_dir/restore-summary.json"
cp "$checklist" "$temporary_dir/release-checklist.md"

rm -f -- "$temporary_dir"/.*.raw "$temporary_dir"/.*.status "$temporary_dir"/.*.timeout
[[ "$(find "$temporary_dir" -mindepth 1 -maxdepth 1 -type f | wc -l | tr -d ' ')" == "9" ]] ||
  fail "validated evidence file set is incomplete"
chmod 0600 "$temporary_dir"/*

mv "$temporary_dir" "$destination"
temporary_dir=""
printf '%s/\n' "$evidence_relative"
for evidence_name in "${evidence_names[@]}"; do
  printf '%s\n' "$evidence_name"
done
echo "PASS"
