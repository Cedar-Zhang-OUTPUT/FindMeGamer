#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "restore rehearsal: $*" >&2
  exit 1
}

[[ "$#" == "1" ]] || fail "usage: $0 s3://bucket/key.dump"
dump_uri="$1"
dry_run="${FMG_DRY_RUN:-0}"
[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "FMG_DRY_RUN must be 0 or 1"

require_environment() {
  local name="$1"
  [[ -n "${!name:-}" ]] || fail "$name is required"
}

require_environment FMG_S3_BUCKET
require_environment FMG_AWS_REGION

[[ "$FMG_S3_BUCKET" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ ]] ||
  fail "FMG_S3_BUCKET is invalid"
[[ "$FMG_AWS_REGION" =~ ^[a-z0-9-]+$ ]] || fail "FMG_AWS_REGION is invalid"
restore_database="find_me_gamer_restore_test"
expected_uri_prefix="s3://${FMG_S3_BUCKET}/"
[[ "$dump_uri" == "$expected_uri_prefix"*.dump ]] ||
  fail "dump URI must be a .dump object in the configured backup bucket"
object_suffix="${dump_uri#"$expected_uri_prefix"}"
[[ -n "$object_suffix" && "$object_suffix" =~ ^[A-Za-z0-9._/-]+\.dump$ ]] ||
  fail "dump URI contains an invalid object key"
checksum_uri="${dump_uri}.sha256"

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
temp_dir=""
database_created=false

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

create_sql='CREATE DATABASE "find_me_gamer_restore_test" TEMPLATE template0;'
drop_sql='DROP DATABASE IF EXISTS "find_me_gamer_restore_test";'
revision_sql='SELECT version_num FROM alembic_version;'
required_tables=(
  game_profiles
  creator_profiles
  analysis_jobs
  match_tasks
  outreach_campaigns
  deliveries
)

plan_psql() {
  local database="$1"
  local sql="$2"
  printf "docker compose --project-directory %q exec -T postgres sh -eu -c 'exec psql --username \"\$POSTGRES_USER\" --dbname \"\$1\" --set ON_ERROR_STOP=1 --tuples-only --no-align --command \"\$2\"' sh %q '%s'\n" \
    "$repo_root" "$database" "$sql"
}

container_psql() {
  local database="$1"
  local sql="$2"
  docker compose --project-directory "$repo_root" exec -T postgres \
    sh -eu -c \
    'exec psql --username "$POSTGRES_USER" --dbname "$1" --set ON_ERROR_STOP=1 --tuples-only --no-align --command "$2"' \
    sh "$database" "$sql"
}

drop_restore_database() {
  if [[ "$dry_run" == "1" ]]; then
    plan_psql postgres "$drop_sql"
  else
    container_psql postgres "$drop_sql" >&2
  fi
}

cleanup() {
  local status="$?"
  trap - EXIT
  if [[ "$database_created" == true ]]; then
    if ! drop_restore_database; then
      echo "restore rehearsal: failed to clean the isolated database" >&2
      if [[ "$status" == "0" ]]; then
        status=1
      fi
    fi
  fi
  if [[ -n "$temp_dir" ]]; then
    rm -rf -- "$temp_dir"
  fi
  exit "$status"
}
trap cleanup EXIT

if [[ "$dry_run" == "1" ]]; then
  dump_file="/tmp/find-me-gamer-restore/test.dump"
  checksum_file="${dump_file}.sha256"
  print_command aws s3 cp "$dump_uri" "$dump_file" --region "$FMG_AWS_REGION" \
    --only-show-errors
  print_command aws s3 cp "$checksum_uri" "$checksum_file" --region "$FMG_AWS_REGION" \
    --only-show-errors
  printf 'sha256sum-or-shasum %q # verify against %q\n' "$dump_file" "$checksum_file"
  print_command docker compose --project-directory "$repo_root" run --rm --no-deps -T \
    api alembic heads
  plan_psql postgres "$create_sql"
  database_created=true
  if [[ "${FMG_DRY_RUN_FAIL_AFTER_CREATE:-0}" == "1" ]]; then
    fail "simulated failure after isolated database creation"
  fi
  printf "docker compose --project-directory %q exec -T postgres sh -eu -c 'exec pg_restore --exit-on-error --no-owner --no-acl --username \"\$POSTGRES_USER\" --dbname \"\$1\"' sh %q < %q\n" \
    "$repo_root" "$restore_database" "$dump_file"
  plan_psql "$restore_database" "$revision_sql"
  for table in "${required_tables[@]}"; do
    plan_psql "$restore_database" "SELECT count(*) FROM $table;"
  done
  drop_restore_database
  database_created=false
  printf 'Restore rehearsal succeeded for %s.\n' "$dump_uri"
  exit 0
fi

for command_name in docker aws mktemp; do
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required"
done

temp_dir="$(mktemp -d /tmp/find-me-gamer-restore.XXXXXX)"
[[ "$temp_dir" == /tmp/find-me-gamer-restore.* && -d "$temp_dir" ]] ||
  fail "mktemp returned an unsafe restore directory"
chmod 0700 "$temp_dir"
dump_file="$temp_dir/test.dump"
checksum_file="${dump_file}.sha256"

echo "Downloading backup and checksum from S3." >&2
aws s3 cp "$dump_uri" "$dump_file" --region "$FMG_AWS_REGION" \
  --only-show-errors >&2
aws s3 cp "$checksum_uri" "$checksum_file" --region "$FMG_AWS_REGION" \
  --only-show-errors >&2

IFS=' ' read -r expected_digest _ <"$checksum_file" ||
  fail "unable to read backup checksum"
[[ "$expected_digest" =~ ^[0-9a-fA-F]{64}$ ]] || fail "stored backup checksum is invalid"
actual_digest="$(sha256_digest "$dump_file")"
[[ "$actual_digest" =~ ^[0-9a-fA-F]{64}$ ]] || fail "calculated backup checksum is invalid"
[[ "$actual_digest" == "$expected_digest" ]] || fail "backup checksum verification failed"

repository_head_output="$(
  docker compose --project-directory "$repo_root" run --rm --no-deps -T \
    api alembic heads
)"
repository_head="$(awk 'NF {print $1}' <<<"$repository_head_output")"
[[ "$repository_head" =~ ^[A-Za-z0-9_]+$ ]] ||
  fail "repository must have exactly one valid Alembic head"

echo "Creating isolated restore database." >&2
docker compose --project-directory "$repo_root" exec -T postgres \
  sh -eu -c 'test "$POSTGRES_DB" != "$1"' sh "$restore_database"
container_psql postgres "$create_sql" >&2
database_created=true

docker compose --project-directory "$repo_root" exec -T postgres \
  sh -eu -c \
  'exec pg_restore --exit-on-error --no-owner --no-acl --username "$POSTGRES_USER" --dbname "$1"' \
  sh "$restore_database" <"$dump_file"

restored_head="$(
  container_psql "$restore_database" "$revision_sql"
)"
restored_head="$(tr -d '[:space:]' <<<"$restored_head")"
[[ "$restored_head" == "$repository_head" ]] ||
  fail "restored Alembic revision does not match repository head"

for table in "${required_tables[@]}"; do
  count="$(
    container_psql "$restore_database" "SELECT count(*) FROM $table;"
  )"
  count="$(tr -d '[:space:]' <<<"$count")"
  [[ "$count" =~ ^[0-9]+$ ]] || fail "$table count verification failed"
  printf '%s rows: %s\n' "$table" "$count" >&2
done

drop_restore_database
database_created=false
printf 'Restore rehearsal succeeded for %s.\n' "$dump_uri"
