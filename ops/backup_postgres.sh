#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "backup: $*" >&2
  exit 1
}

dry_run="${FMG_DRY_RUN:-0}"
[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "FMG_DRY_RUN must be 0 or 1"

marker="regular"
case "$#" in
  0) ;;
  1)
    [[ "$1" == "--pre-migration" ]] || fail "usage: $0 [--pre-migration]"
    marker="pre-migration"
    ;;
  *) fail "usage: $0 [--pre-migration]" ;;
esac

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "$name is required"
}

require_environment FMG_S3_BUCKET
require_environment FMG_AWS_REGION
require_environment FMG_BACKUP_PREFIX

[[ "$FMG_S3_BUCKET" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ ]] ||
  fail "FMG_S3_BUCKET is invalid"
[[ "$FMG_AWS_REGION" =~ ^[a-z0-9-]+$ ]] || fail "FMG_AWS_REGION is invalid"
[[ "$FMG_BACKUP_PREFIX" =~ ^[A-Za-z0-9._/-]+/$ ]] ||
  fail "FMG_BACKUP_PREFIX must be a slash-terminated key prefix"
[[ "$FMG_BACKUP_PREFIX" != /* && "$FMG_BACKUP_PREFIX" != *'//'* ]] ||
  fail "FMG_BACKUP_PREFIX must be relative and normalized"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
compose_command=(docker compose --project-directory "$repo_root")
if [[ -n "${FMG_COMPOSE_ENV_FILE:-}" ]]; then
  [[ "$FMG_COMPOSE_ENV_FILE" == /* && -f "$FMG_COMPOSE_ENV_FILE" &&
    ! -L "$FMG_COMPOSE_ENV_FILE" ]] ||
    fail "FMG_COMPOSE_ENV_FILE must be an absolute regular non-symlink file"
  compose_command+=(--env-file "$FMG_COMPOSE_ENV_FILE")
fi

if [[ "$dry_run" == "1" ]]; then
  timestamp="${FMG_DRY_RUN_TIMESTAMP:-20000101T000000Z}"
  commit_id="${FMG_DRY_RUN_COMMIT:-000000000000}"
else
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  commit_id="$(git -C "$repo_root" rev-parse --short=12 HEAD)"
fi
[[ "$timestamp" =~ ^[0-9]{8}T[0-9]{6}Z$ ]] || fail "backup timestamp is invalid"
[[ "$commit_id" =~ ^[0-9a-fA-F]{7,40}$ ]] || fail "commit identity is invalid"

dump_name="${timestamp}-${commit_id}-${marker}.dump"
dump_uri="s3://${FMG_S3_BUCKET}/${FMG_BACKUP_PREFIX}${dump_name}"
checksum_uri="${dump_uri}.sha256"
dump_container_command='exec pg_dump --format=custom --no-owner --no-acl --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"'

print_command() {
  local argument
  local separator=""
  for argument in "$@"; do
    printf '%s%q' "$separator" "$argument"
    separator=" "
  done
  printf '\n'
}

sha256_digest() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  else
    fail "sha256sum or shasum is required"
  fi
}

if [[ "$dry_run" == "1" ]]; then
  dump_file="/tmp/find-me-gamer-backup/$dump_name"
  checksum_file="${dump_file}.sha256"
  printf 'docker compose --project-directory %q' "$repo_root"
  if [[ -n "${FMG_COMPOSE_ENV_FILE:-}" ]]; then
    printf ' --env-file %q' "$FMG_COMPOSE_ENV_FILE"
  fi
  printf " exec -T postgres sh -eu -c '%s' > %q\n" \
    "$dump_container_command" "$dump_file"
  printf 'sha256sum-or-shasum %q > %q\n' "$dump_file" "$checksum_file"
  print_command aws s3 cp "$dump_file" "$dump_uri" --sse AES256 \
    --region "$FMG_AWS_REGION" --only-show-errors
  print_command aws s3 cp "$checksum_file" "$checksum_uri" --sse AES256 \
    --region "$FMG_AWS_REGION" --only-show-errors
  printf '%s\n' "$dump_uri"
  exit 0
fi

for command_name in docker aws git date mktemp; do
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required"
done

temp_dir="$(mktemp -d /tmp/find-me-gamer-backup.XXXXXX)"
[[ "$temp_dir" == /tmp/find-me-gamer-backup.* && -d "$temp_dir" ]] ||
  fail "mktemp returned an unsafe backup directory"
chmod 0700 "$temp_dir"
cleanup() {
  rm -rf -- "$temp_dir"
}
trap cleanup EXIT

dump_file="$temp_dir/$dump_name"
checksum_file="${dump_file}.sha256"

echo "Creating PostgreSQL custom-format backup." >&2
"${compose_command[@]}" exec -T postgres \
  sh -eu -c "$dump_container_command" >"$dump_file"
[[ -s "$dump_file" ]] || fail "pg_dump produced an empty backup"

digest="$(sha256_digest "$dump_file")"
[[ "$digest" =~ ^[0-9a-fA-F]{64}$ ]] || fail "backup checksum is invalid"
printf '%s  %s\n' "$digest" "$dump_name" >"$checksum_file"

echo "Uploading encrypted dump and checksum to S3." >&2
aws s3 cp "$dump_file" "$dump_uri" --sse AES256 \
  --region "$FMG_AWS_REGION" --only-show-errors >&2
aws s3 cp "$checksum_file" "$checksum_uri" --sse AES256 \
  --region "$FMG_AWS_REGION" --only-show-errors >&2

printf '%s\n' "$dump_uri"
