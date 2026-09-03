#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "creator-seed: $*" >&2
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

require_private_file() {
  local candidate="$1"
  local label="$2"
  local owner_id
  [[ -f "$candidate" && ! -L "$candidate" ]] || fail "$label must be a regular non-symlink file"
  [[ "$(file_mode "$candidate")" == "600" ]] || fail "$label must have mode 0600"
  owner_id="$(file_owner_id "$candidate")"
  [[ "$owner_id" == "0" || "$owner_id" == "$(id -u)" ]] || fail "$label has an invalid owner"
}

validate_dry_run_fixture() {
  awk -F, '
    BEGIN { prefix = "https://www.youtube.com/channel/UC"; failed = 0 }
    NR == 1 {
      if ($0 != "youtube_url,contact_email,notes") failed = 1
      next
    }
    {
      suffix = substr($1, length(prefix) + 1)
      if (NF != 3 || $2 != "" || $3 != "" || index($1, prefix) != 1 ||
          length(suffix) != 22 || suffix !~ /^[A-Za-z0-9_-]+$/ || seen[$1]++) failed = 1
    }
    END {
      if (NR != 101) failed = 1
      exit failed
    }
  ' "$1"
}

print_command() {
  local argument
  local separator=""
  for argument in "$@"; do
    printf '%s%q' "$separator" "$argument"
    separator=" "
  done
  printf '\n'
}

[[ $# -eq 1 ]] || fail "usage: $0 <creator-csv>"
csv_path="$1"
dry_run="${FMG_DRY_RUN:-0}"
test_mode="${FMG_OPERATOR_TEST_MODE:-0}"
[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "FMG_DRY_RUN must be 0 or 1"
[[ "$test_mode" == "0" || "$test_mode" == "1" ]] || fail "test mode must be 0 or 1"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd "$script_dir/.." && pwd)"
fixture_path="${repository_root}/ops/tests/fixtures/creator-seed-100.csv"

if [[ "$dry_run" == "1" ]]; then
  [[ -f "$csv_path" && ! -L "$csv_path" ]] || fail "dry-run CSV must be a regular non-symlink file"
  dry_csv_canonical="$(cd "$(dirname "$csv_path")" && pwd -P)/$(basename "$csv_path")"
  dry_fixture_canonical="$(cd "$(dirname "$fixture_path")" && pwd -P)/$(basename "$fixture_path")"
  [[ "$dry_csv_canonical" == "$dry_fixture_canonical" ]] || fail "dry-run accepts only the checked-in synthetic fixture"
  validate_dry_run_fixture "$csv_path" 2>/dev/null || fail "dry-run CSV requires the exact header and 100 unique supported Channel URLs"
  printf 'DRY RUN: synthetic Creator fixture validation passed; no Docker or provider call was made.\n'
  dry_compose=(docker compose --project-directory /opt/find-me-gamer --env-file /etc/find-me-gamer/app.env)
  dry_dir='/tmp/find-me-gamer-seed-<random-hex>'
  print_command "${dry_compose[@]}" ps --format json api worker
  print_command "${dry_compose[@]}" exec -T api mkdir -m 700 -- "$dry_dir"
  print_command "${dry_compose[@]}" cp "$csv_path" "api:${dry_dir}/creators.csv"
  print_command "${dry_compose[@]}" exec -T api python -c '<validate-exact-100-row-csv>' "${dry_dir}/creators.csv"
  print_command "${dry_compose[@]}" exec -T api python -m app.cli.seed_creators "${dry_dir}/creators.csv" --report "${dry_dir}/report.json"
  print_command "${dry_compose[@]}" cp "api:${dry_dir}/report.json" '<private-adjacent-host-temp>'
  printf 'validate report; atomically replace adjacent mode-0600 report\n'
  print_command "${dry_compose[@]}" exec -T api rm -f -- "${dry_dir}/creators.csv"
  print_command "${dry_compose[@]}" exec -T api rm -f -- "${dry_dir}/report.json"
  print_command "${dry_compose[@]}" exec -T api rmdir -- "$dry_dir"
  exit 0
fi

[[ "$csv_path" == /* ]] || fail "Creator CSV must be an absolute path"
[[ "$csv_path" != *$'\n'* && "$csv_path" != *$'\r'* ]] || fail "Creator CSV path contains control characters"
require_private_file "$csv_path" "Creator CSV"
umask 077
csv_canonical="$(cd "$(dirname "$csv_path")" && pwd -P)/$(basename "$csv_path")"

repo_root="/opt/find-me-gamer"
env_file="/etc/find-me-gamer/app.env"
docker_bin="docker"
if [[ "$test_mode" == "1" ]]; then
  repo_root="${FMG_SEED_REPO_ROOT:?FMG_SEED_REPO_ROOT is required in test mode}"
  env_file="${FMG_SEED_ENV_FILE:?FMG_SEED_ENV_FILE is required in test mode}"
  docker_bin="${FMG_DOCKER_BIN:?FMG_DOCKER_BIN is required in test mode}"
else
  [[ -z "${FMG_SEED_REPO_ROOT:-}${FMG_SEED_ENV_FILE:-}${FMG_DOCKER_BIN:-}" ]] || fail "path overrides are allowed only in test mode"
  [[ "$(id -u)" == "0" ]] || fail "production Creator seed must run as root"
  [[ "$repository_root" == "$repo_root" && "$PWD" == "$repo_root" ]] || fail "production Creator seed must run from /opt/find-me-gamer"
  fixture_canonical="$(cd "$(dirname "$fixture_path")" && pwd -P)/$(basename "$fixture_path")"
  [[ "$csv_canonical" != "$fixture_canonical" ]] || fail "the checked-in synthetic fixture cannot be used live"
fi
require_private_file "$env_file" "protected app.env"

report_path="${csv_path}.report.json"
if [[ -e "$report_path" || -L "$report_path" ]]; then
  require_private_file "$report_path" "Creator seed report"
fi

unset BACKEND_SUBNET FMG_AWS_REGION FMG_S3_BUCKET POSTGRES_DB POSTGRES_PASSWORD \
  POSTGRES_USER SERVICE_DOMAIN WORKSPACE_ACCESS_KEY_HASH
compose=(
  "$docker_bin" compose --project-directory "$repo_root" --env-file "$env_file"
)

service_state="$("${compose[@]}" ps --format json api worker 2>/dev/null)" || fail "API/Worker health could not be checked"
printf '%s\n' "$service_state" | jq -se '
  length == 2 and
  ([.[].Service] | sort) == ["api", "worker"] and
  all(.[]; .State == "running" and .Health == "healthy")
' >/dev/null 2>&1 || fail "API and Worker must both be running and healthy"
unset service_state

seed_hex="$(openssl rand -hex 16)" || fail "temporary seed identity could not be generated"
[[ "$seed_hex" =~ ^[0-9a-f]{32}$ ]] || fail "temporary seed identity is invalid"
container_dir="/tmp/find-me-gamer-seed-${seed_hex}"
container_csv="${container_dir}/creators.csv"
container_report="${container_dir}/report.json"
[[ "$container_dir" =~ ^/tmp/find-me-gamer-seed-[0-9a-f]{32}$ ]] || fail "temporary container path is invalid"

container_created=0
report_captured=0
host_temporary=""
report_counts=""

csv_validation_program='import csv,re,sys,unicodedata
from pathlib import Path
from urllib.parse import urlsplit
channel=re.compile(r"/channel/UC[A-Za-z0-9_-]{6,126}/?")
handle=re.compile(r"/@[A-Za-z0-9._-]{3,30}/?")
def supported(raw):
 if (not raw or len(raw)>2048
  or any(character.isspace() or unicodedata.category(character).startswith("C") for character in raw)):
  return False
 parsed=urlsplit(raw)
 try:
  port=parsed.port
 except ValueError:
  return False
 return (parsed.scheme=="https" and parsed.hostname in {"youtube.com","www.youtube.com"}
  and parsed.username is None and parsed.password is None and port is None
  and parsed.netloc.casefold()==parsed.hostname.casefold()
  and not parsed.query and not parsed.fragment
  and "%" not in parsed.path and "\\" not in parsed.path
  and (channel.fullmatch(parsed.path) is not None or handle.fullmatch(parsed.path) is not None))
with Path(sys.argv[1]).open(encoding="utf-8",newline="") as stream:
 rows=list(csv.reader(stream,strict=True))
assert rows and rows[0]==["youtube_url","contact_email","notes"]
assert len(rows[1:])==100, "seed CSV must contain exactly 100 rows"
urls=[row[0] for row in rows[1:]]
assert all(len(row)==3 and row[0] and supported(row[0]) for row in rows[1:])
assert len(set(urls))==100'

report_validation_program='import sys
from pathlib import Path
from app.cli.seed_creators import load_seed_report,load_seed_source
source=load_seed_source(Path(sys.argv[1]))
assert len(source.rows)==100
report=load_seed_report(Path(sys.argv[2]),source=source)
assert len(report.rows)==100
incomplete=sum(row.status=="incomplete" for row in report.rows)
counts=report.counts
print(counts["queued"],counts["duplicate"],counts["failed"],incomplete)'

capture_report() {
  local counts
  counts="$("${compose[@]}" exec -T api python -c "$report_validation_program" "$container_csv" "$container_report" 2>/dev/null)" || return 1
  [[ "$counts" =~ ^[0-9]+\ [0-9]+\ [0-9]+\ [0-9]+$ ]] || return 1
  host_temporary="$(mktemp "${report_path}.tmp.XXXXXX")" || return 1
  chmod 600 "$host_temporary"
  "${compose[@]}" cp "api:${container_report}" "$host_temporary" >/dev/null 2>&1 || return 1
  chmod 600 "$host_temporary"
  mv -f -- "$host_temporary" "$report_path" || return 1
  host_temporary=""
  report_counts="$counts"
  report_captured=1
}

cleanup_container() {
  [[ "$container_created" == "1" ]] || return 0
  local cleanup_failed=0
  if ! "${compose[@]}" exec -T api rm -f -- "$container_csv" >/dev/null 2>&1; then
    cleanup_failed=1
  fi
  if ! "${compose[@]}" exec -T api rm -f -- "$container_report" >/dev/null 2>&1; then
    cleanup_failed=1
  fi
  if ! "${compose[@]}" exec -T api rmdir -- "$container_dir" >/dev/null 2>&1; then
    cleanup_failed=1
  fi
  return "$cleanup_failed"
}

finish() {
  finish_status=$?
  trap - EXIT INT TERM
  if [[ "$container_created" == "1" && "$report_captured" == "0" ]]; then
    capture_report >/dev/null 2>&1 || true
  fi
  cleanup_status=0
  cleanup_container || cleanup_status=$?
  if [[ -n "$host_temporary" && -f "$host_temporary" && ! -L "$host_temporary" ]]; then
    rm -f -- "$host_temporary" || cleanup_status=1
  fi
  if [[ "$cleanup_status" -ne 0 ]]; then
    echo "creator-seed: temporary container cleanup failed" >&2
    if [[ "$finish_status" -eq 0 ]]; then
      finish_status=1
    fi
  fi
  exit "$finish_status"
}
trap finish EXIT
trap 'exit 130' INT TERM

"${compose[@]}" exec -T api mkdir -m 700 -- "$container_dir" >/dev/null 2>&1 || fail "temporary container directory could not be created"
container_created=1
"${compose[@]}" cp "$csv_path" "api:${container_csv}" >/dev/null 2>&1 || fail "Creator CSV could not be copied for validation"
"${compose[@]}" exec -T api python -c "$csv_validation_program" "$container_csv" >/dev/null 2>&1 || fail "Creator CSV must use the exact header and contain 100 unique supported Channel URLs"

if [[ -f "$report_path" ]]; then
  "${compose[@]}" cp "$report_path" "api:${container_report}" >/dev/null 2>&1 || fail "existing seed report could not be copied for resume"
fi

set +e
"${compose[@]}" exec -T api python -m app.cli.seed_creators \
  "$container_csv" --report "$container_report" >/dev/null 2>&1
cli_status=$?
set -e
capture_report || fail "seed report could not be validated and saved"
read -r queued_count duplicate_count failed_count incomplete_count <<<"$report_counts"
printf 'Creator seed: queued=%s duplicate=%s failed=%s incomplete=%s\n' \
  "$queued_count" "$duplicate_count" "$failed_count" "$incomplete_count"
printf 'Creator seed report: %s\n' "$report_path"
if [[ "$cli_status" -ne 0 || "$failed_count" -ne 0 || "$incomplete_count" -ne 0 ||
  $((queued_count + duplicate_count + failed_count + incomplete_count)) -ne 100 ]]; then
  fail "Creator seed is incomplete; correct failed rows and rerun with the same CSV and report"
fi
