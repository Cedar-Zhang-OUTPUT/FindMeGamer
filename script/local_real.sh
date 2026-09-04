#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "local-real: $*" >&2
  exit 1
}

usage() {
  echo "usage: $0 start [--beat] | stop | status | logs [api|worker|beat|postgres|redis] | key" >&2
  exit 64
}

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
state_dir="${repository_root}/.local/find-me-gamer"
if [[ "${FMG_LOCAL_TEST_MODE:-0}" == "1" ]]; then
  state_dir="${FMG_LOCAL_TEST_STATE_DIR:?FMG_LOCAL_TEST_STATE_DIR is required in test mode}"
elif [[ -n "${FMG_LOCAL_TEST_STATE_DIR:-}" ]]; then
  fail "state directory overrides are allowed only in test mode"
fi

env_file="${state_dir}/compose.env"
master_key_file="${state_dir}/master.key"
workspace_key_file="${state_dir}/workspace.key"
workspace_hash_file="${state_dir}/workspace.hash"
postgres_password_file="${state_dir}/postgres.password"
project_name="find-me-gamer-local"
base_compose="${repository_root}/compose.yaml"
local_compose="${repository_root}/compose.local.yaml"

command_name="${1:-}"
shift || true

case "$command_name" in
  start)
    beat_enabled=0
    if [[ "${1:-}" == "--beat" ]]; then
      beat_enabled=1
      shift
    fi
    (( $# == 0 )) || usage
    ;;
  stop|status|key)
    (( $# == 0 )) || usage
    ;;
  logs)
    (( $# <= 1 )) || usage
    if (( $# == 1 )); then
      case "$1" in
        api|worker|beat|postgres|redis) ;;
        *) usage ;;
      esac
    fi
    ;;
  *) usage ;;
esac

file_mode() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    stat -f '%Lp' "$1"
  else
    stat -c '%a' "$1"
  fi
}

require_private_file() {
  local path="$1"
  [[ -f "$path" && ! -L "$path" ]] || fail "$path is missing or unsafe"
  [[ "$(file_mode "$path")" == "600" ]] || fail "$path must have mode 0600"
}

write_generated_secret() {
  local destination="$1"
  shift
  local temporary
  temporary="$(mktemp "${state_dir}/.secret.XXXXXX")"
  if ! openssl "$@" | tr -d '\n' >"$temporary"; then
    rm -f "$temporary"
    fail "could not generate local credentials"
  fi
  [[ -s "$temporary" && "$(wc -l <"$temporary" | tr -d ' ')" == "0" ]] || {
    rm -f "$temporary"
    fail "generated local credential was invalid"
  }
  chmod 600 "$temporary"
  mv "$temporary" "$destination"
}

write_private_value() {
  local destination="$1"
  local value="$2"
  local temporary
  temporary="$(mktemp "${state_dir}/.value.XXXXXX")"
  printf '%s' "$value" >"$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$destination"
}

initialize_secret_files() {
  umask 077
  if [[ -e "$state_dir" && ( ! -d "$state_dir" || -L "$state_dir" ) ]]; then
    fail "$state_dir must be a private directory"
  fi
  mkdir -p "$state_dir"
  chmod 700 "$state_dir"

  if [[ ! -e "$master_key_file" ]]; then
    write_generated_secret "$master_key_file" rand -base64 32
  fi
  if [[ ! -e "$workspace_key_file" ]]; then
    write_generated_secret "$workspace_key_file" rand -hex 24
  fi
  if [[ ! -e "$postgres_password_file" ]]; then
    write_generated_secret "$postgres_password_file" rand -hex 24
  fi

  require_private_file "$master_key_file"
  require_private_file "$workspace_key_file"
  require_private_file "$postgres_password_file"
  [[ "$(read_private_value "$workspace_key_file")" =~ ^[0-9a-f]{48}$ ]] ||
    fail "local Workspace Access Key is invalid"
  if [[ -e "$workspace_hash_file" ]]; then
    require_private_file "$workspace_hash_file"
  fi
}

read_private_value() {
  local path="$1"
  local value
  IFS= read -r value <"$path" || [[ -n "$value" ]] || fail "$path is empty"
  [[ -n "$value" && "$value" != *$'\n'* && "$value" != *$'\r'* ]] ||
    fail "$path must contain one non-empty line"
  printf '%s' "$value"
}

render_environment() {
  local workspace_hash="$1"
  local postgres_password
  local temporary
  postgres_password="$(read_private_value "$postgres_password_file")"
  [[ "$postgres_password" =~ ^[0-9a-f]{48}$ ]] || fail "local PostgreSQL credential is invalid"
  [[ "$workspace_hash" == '$argon2id$'* && "$workspace_hash" != *"'"* ]] ||
    fail "local Workspace Access Key hash is invalid"
  [[ "$master_key_file" != *"'"* && "$master_key_file" != *$'\n'* ]] ||
    fail "local state path cannot be represented safely"

  temporary="$(mktemp "${state_dir}/.compose-env.XXXXXX")"
  {
    printf 'SERVICE_DOMAIN=localhost\n'
    printf 'BACKEND_SUBNET=172.31.249.0/24\n'
    printf 'POSTGRES_DB=find_me_gamer_local\n'
    printf 'POSTGRES_USER=find_me_gamer\n'
    printf 'POSTGRES_PASSWORD=%s\n' "$postgres_password"
    printf "WORKSPACE_ACCESS_KEY_HASH='%s'\n" "$workspace_hash"
    printf 'FMG_AWS_REGION=us-east-1\n'
    printf 'FMG_S3_BUCKET=find-me-gamer-local-artifacts\n'
    printf 'ARTIFACT_STORE=filesystem\n'
    printf 'ARTIFACT_DIRECTORY=/var/lib/find-me-gamer/artifacts\n'
    printf "FMG_LOCAL_MASTER_KEY='%s'\n" "$master_key_file"
  } >"$temporary"
  chmod 600 "$temporary"
  mv "$temporary" "$env_file"
}

require_initialized() {
  [[ -d "$state_dir" && ! -L "$state_dir" ]] ||
    fail "local services are not initialized; run '$0 start' first"
  require_private_file "$env_file"
  require_private_file "$master_key_file"
  require_private_file "$workspace_key_file"
  require_private_file "$workspace_hash_file"
  require_private_file "$postgres_password_file"
}

compose_command() {
  local include_beat="$1"
  shift
  local arguments=(
    docker compose
    --project-name "$project_name"
    --project-directory "$repository_root"
    --env-file "$env_file"
    -f "$base_compose"
    -f "$local_compose"
  )
  if [[ "$include_beat" == "1" ]]; then
    arguments+=(--profile beat)
  fi
  "${arguments[@]}" "$@"
}

unset SERVICE_DOMAIN BACKEND_SUBNET POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD \
  WORKSPACE_ACCESS_KEY_HASH FMG_AWS_REGION FMG_S3_BUCKET ARTIFACT_STORE \
  ARTIFACT_DIRECTORY FMG_LOCAL_MASTER_KEY COMPOSE_FILE COMPOSE_PROFILES \
  COMPOSE_PROJECT_NAME AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN \
  WORKSPACE_ACCESS_KEY

if [[ "$command_name" == "key" ]]; then
  [[ -d "$state_dir" && ! -L "$state_dir" ]] ||
    fail "local services are not initialized; run '$0 start' first"
  require_private_file "$workspace_key_file"
  read_private_value "$workspace_key_file"
  printf '\n'
  exit 0
fi

command -v docker >/dev/null 2>&1 || fail "docker is required"

if [[ "$command_name" == "start" ]]; then
  command -v openssl >/dev/null 2>&1 || fail "openssl is required"
  initialize_secret_files

  placeholder_hash='$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0c2FsdA$YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE'
  if [[ -f "$workspace_hash_file" ]]; then
    workspace_hash="$(read_private_value "$workspace_hash_file")"
  else
    workspace_hash="$placeholder_hash"
  fi
  render_environment "$workspace_hash"

  build_services=(api worker)
  if [[ "$beat_enabled" == "1" ]]; then
    build_services+=(beat)
  fi
  compose_command "$beat_enabled" version >/dev/null 2>&1 ||
    fail "Docker Compose v2 is required"
  compose_command "$beat_enabled" build "${build_services[@]}"

  if [[ ! -f "$workspace_hash_file" ]]; then
    workspace_hash="$({
      compose_command "$beat_enabled" run --rm --no-deps -T \
        --entrypoint python api -c \
        'import sys; from app.core.security import hash_workspace_key; print(hash_workspace_key(sys.stdin.read()))'
    } <"$workspace_key_file")"
    [[ "$workspace_hash" == '$argon2id$'* && "$workspace_hash" != *$'\n'* ]] ||
      fail "could not hash the local Workspace Access Key"
    write_private_value "$workspace_hash_file" "$workspace_hash"
    render_environment "$workspace_hash"
  fi

  compose_command "$beat_enabled" config --quiet
  compose_command "$beat_enabled" stop api worker beat >/dev/null 2>&1 || true
  compose_command "$beat_enabled" up -d --wait --wait-timeout 120 postgres redis
  compose_command "$beat_enabled" run --rm --no-deps -T api alembic upgrade head
  application_services=(api worker)
  if [[ "$beat_enabled" == "1" ]]; then
    application_services+=(beat)
  fi
  application_services+=(postgres redis)
  compose_command "$beat_enabled" up -d --wait --wait-timeout 120 \
    "${application_services[@]}"
  echo "Local services are ready at http://127.0.0.1:8000"
  echo "Run '$0 key' to display the Workspace Access Key."
  exit 0
fi

require_initialized
compose_command 1 version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
case "$command_name" in
  stop)
    compose_command 1 down --remove-orphans
    ;;
  status)
    compose_command 1 ps
    ;;
  logs)
    if (( $# == 1 )); then
      compose_command 1 logs --tail 200 "$1"
    else
      compose_command 1 logs --tail 200
    fi
    ;;
esac
