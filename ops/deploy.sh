#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "deploy: $*" >&2
  exit 1
}

validate_ref() {
  local candidate="$1"
  [[ "$candidate" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$ &&
    "$candidate" != *'..'* && "$candidate" != *'//'* &&
    "$candidate" != *'@{'* && "$candidate" != */ && "$candidate" != *. ]] ||
    fail "git ref must use only safe branch, tag, or commit characters"
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

require_protected_file() {
  local path="$1"
  local owner_id="$2"
  [[ -f "$path" && ! -L "$path" ]] || fail "$path must be a regular non-symlink file"
  [[ "$(file_mode "$path")" == "600" ]] || fail "$path must have mode 0600"
  [[ "$(file_owner_id "$path")" == "$owner_id" ]] ||
    fail "$path must be owned by the deployment account"
}

validate_prefix() {
  local value="$1"
  [[ "$value" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*/$ &&
    "$value" != /* && "$value" != *'//'* && "$value" != *'/../'* &&
    "$value" != '../'* && "$value" != *'/./'* && "$value" != './'* ]] ||
    fail "FMG_BACKUP_PREFIX must be a relative normalized slash-terminated prefix"
}

load_deploy_configuration() {
  local line
  local service_domain_count=0
  local bucket_count=0
  local region_count=0
  local backup_count=0

  SERVICE_DOMAIN=""
  FMG_S3_BUCKET=""
  FMG_AWS_REGION=""
  FMG_BACKUP_PREFIX=""
  while IFS= read -r line || [[ -n "$line" ]]; do
    case "$line" in
      SERVICE_DOMAIN=*)
        SERVICE_DOMAIN="${line#*=}"
        service_domain_count=$((service_domain_count + 1))
        ;;
      FMG_S3_BUCKET=*)
        FMG_S3_BUCKET="${line#*=}"
        bucket_count=$((bucket_count + 1))
        ;;
      FMG_AWS_REGION=*)
        FMG_AWS_REGION="${line#*=}"
        region_count=$((region_count + 1))
        ;;
      FMG_BACKUP_PREFIX=*)
        FMG_BACKUP_PREFIX="${line#*=}"
        backup_count=$((backup_count + 1))
        ;;
    esac
  done <"$env_file"

  [[ "$service_domain_count" == "1" && "$bucket_count" == "1" &&
    "$region_count" == "1" && "$backup_count" == "1" ]] ||
    fail "protected app.env must contain each deployment setting exactly once"
  [[ "$SERVICE_DOMAIN" =~ ^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$ &&
    "$SERVICE_DOMAIN" == *.* && "$SERVICE_DOMAIN" != *'..'* ]] ||
    fail "SERVICE_DOMAIN is invalid"
  [[ "$FMG_S3_BUCKET" =~ ^[a-z0-9][a-z0-9.-]*[a-z0-9]$ ]] ||
    fail "FMG_S3_BUCKET is invalid"
  [[ "$FMG_AWS_REGION" =~ ^[a-z0-9-]+$ ]] || fail "FMG_AWS_REGION is invalid"
  validate_prefix "$FMG_BACKUP_PREFIX"
  export SERVICE_DOMAIN FMG_S3_BUCKET FMG_AWS_REGION FMG_BACKUP_PREFIX
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

dry_run="${FMG_DRY_RUN:-0}"
test_mode="${FMG_DEPLOY_TEST_MODE:-0}"
[[ "$dry_run" == "0" || "$dry_run" == "1" ]] || fail "FMG_DRY_RUN must be 0 or 1"
[[ "$test_mode" == "0" || "$test_mode" == "1" ]] ||
  fail "FMG_DEPLOY_TEST_MODE must be 0 or 1"
(( $# <= 1 )) || fail "usage: $0 [git-ref]"
requested_ref="${1:-main}"
validate_ref "$requested_ref"

if [[ "$dry_run" == "1" ]]; then
  dry_repo_root="/opt/find-me-gamer"
  dry_env_file="/etc/find-me-gamer/app.env"
  dry_compose=(docker compose --project-directory "$dry_repo_root" --env-file "$dry_env_file")
  printf 'acquire nonblocking lock /var/lock/find-me-gamer-deploy.lock\n'
  print_command git -C "$dry_repo_root" fetch --prune origin
  printf 'resolve existing ref %q to <resolved-commit>\n' "$requested_ref"
  printf 'git -C %s checkout --detach <resolved-commit>\n' "$dry_repo_root"
  print_command "${dry_compose[@]}" build
  print_command "${dry_compose[@]}" stop proxy api worker beat
  print_command "${dry_compose[@]}" up -d --wait --wait-timeout 120 postgres redis
  printf 'FMG_COMPOSE_ENV_FILE=%q ' "$dry_env_file"
  print_command "$dry_repo_root/ops/backup_postgres.sh" --pre-migration
  print_command "${dry_compose[@]}" run --rm --no-deps -T api alembic upgrade head
  print_command "${dry_compose[@]}" up -d
  printf 'poll https://${SERVICE_DOMAIN}/health/ready for no more than 120 seconds\n'
  print_command "${dry_compose[@]}" ps
  printf 'print the exact deployed commit\n'
  exit 0
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
env_file="/etc/find-me-gamer/app.env"
master_key_file="/etc/find-me-gamer/master.key"
lock_file="/var/lock/find-me-gamer-deploy.lock"
required_owner=0

if [[ "$test_mode" == "1" ]]; then
  env_file="${FMG_DEPLOY_ENV_FILE:?FMG_DEPLOY_ENV_FILE is required in test mode}"
  master_key_file="${FMG_DEPLOY_MASTER_KEY_FILE:?FMG_DEPLOY_MASTER_KEY_FILE is required in test mode}"
  lock_file="${FMG_DEPLOY_LOCK_FILE:?FMG_DEPLOY_LOCK_FILE is required in test mode}"
  required_owner="$(id -u)"
else
  [[ -z "${FMG_DEPLOY_ENV_FILE:-}${FMG_DEPLOY_MASTER_KEY_FILE:-}${FMG_DEPLOY_LOCK_FILE:-}" ]] ||
    fail "deployment path overrides are allowed only in test mode"
  [[ "$(id -u)" == "0" ]] || fail "production deployment must run as root"
  [[ "$repo_root" == "/opt/find-me-gamer" ]] ||
    fail "production deployment must run from /opt/find-me-gamer"
fi

require_protected_file "$env_file" "$required_owner"
require_protected_file "$master_key_file" "$required_owner"
load_deploy_configuration
unset BACKEND_SUBNET POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
  WORKSPACE_ACCESS_KEY_HASH

for command_name in flock git docker curl date; do
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required"
done
compose=(docker compose --project-directory "$repo_root" --env-file "$env_file")
"${compose[@]}" version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
[[ -x "$repo_root/ops/backup_postgres.sh" ]] || fail "backup_postgres.sh is required"

exec 9>"$lock_file"
flock -n 9 || fail "another deployment holds $lock_file"

[[ -z "$(git -C "$repo_root" status --porcelain)" ]] ||
  fail "server checkout must be clean before deployment"
git -C "$repo_root" fetch --prune origin

resolved_commit=""
if resolved_commit="$(
  git -C "$repo_root" rev-parse --verify --quiet \
    "refs/remotes/origin/${requested_ref}^{commit}"
)"; then
  :
elif resolved_commit="$(git -C "$repo_root" rev-parse --verify --quiet "${requested_ref}^{commit}")"; then
  :
else
  fail "requested git ref does not resolve to an existing commit"
fi
[[ "$resolved_commit" =~ ^[0-9a-fA-F]{40}$ ]] || fail "resolved commit is invalid"
git -C "$repo_root" checkout --detach "$resolved_commit"
deployed_commit="$(git -C "$repo_root" rev-parse HEAD)"
[[ "$deployed_commit" == "$resolved_commit" ]] || fail "checked out commit did not match resolution"

"${compose[@]}" build

"${compose[@]}" stop proxy api worker beat
"${compose[@]}" up -d --wait --wait-timeout 120 postgres redis

backup_uri=""
if ! backup_uri="$(
  FMG_COMPOSE_ENV_FILE="$env_file" "$repo_root/ops/backup_postgres.sh" --pre-migration
)"; then
  fail "pre-migration backup failed; application services remain stopped"
fi
[[ "$backup_uri" == "s3://${FMG_S3_BUCKET}/${FMG_BACKUP_PREFIX}"*'-pre-migration.dump' &&
  "$backup_uri" != *$'\n'* ]] ||
  fail "pre-migration backup returned an invalid success URI"
printf 'Pre-migration backup: %s\n' "$backup_uri"

if ! "${compose[@]}" run --rm --no-deps -T api alembic upgrade head; then
  fail "migration failed; application services remain stopped"
fi
"${compose[@]}" up -d

health_timeout=120
health_started="$(date +%s)"
health_deadline=$((health_started + health_timeout))
ready=0
while :; do
  health_now="$(date +%s)"
  (( health_now < health_deadline )) || break
  remaining=$((health_deadline - health_now))
  attempt_timeout=3
  (( remaining >= attempt_timeout )) || attempt_timeout="$remaining"
  if curl --fail --silent --show-error --connect-timeout 2 \
    --max-time "$attempt_timeout" "https://${SERVICE_DOMAIN}/health/ready" \
    >/dev/null 2>&1; then
    ready=1
    break
  fi
  health_now="$(date +%s)"
  (( health_now < health_deadline )) || break
  sleep 2
done

if [[ "$ready" != "1" ]]; then
  "${compose[@]}" ps >&2 || true
  fail "HTTPS readiness did not succeed within 120 seconds"
fi

"${compose[@]}" ps
printf 'Deployed commit: %s\n' "$deployed_commit"
