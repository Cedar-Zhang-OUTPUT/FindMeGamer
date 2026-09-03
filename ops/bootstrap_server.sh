#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "bootstrap: $*" >&2
  exit 1
}

test_mode=false
case "${1:-}" in
  "") ;;
  --test-mode) test_mode=true ;;
  *) fail "usage: $0 [--test-mode]" ;;
esac
if (( $# > 1 )); then
  fail "usage: $0 [--test-mode]"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
env_template="$repo_root/.env.example"

if [[ "$test_mode" == true ]]; then
  etc_dir="${FMG_ETC_DIR:?FMG_ETC_DIR is required in test mode}"
  app_dir="${FMG_APP_DIR:?FMG_APP_DIR is required in test mode}"
else
  if [[ -n "${FMG_ETC_DIR:-}" || -n "${FMG_APP_DIR:-}" ]]; then
    fail "directory overrides are allowed only in test mode"
  fi
  if [[ "$(id -u)" != "0" ]]; then
    fail "production bootstrap must run as root"
  fi
  etc_dir="/etc/find-me-gamer"
  app_dir="/opt/find-me-gamer"
fi

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

validate_production_prerequisites() {
  local aws_version

  require_command docker
  require_command curl
  require_command jq
  require_command openssl
  require_command aws
  require_command systemctl

  docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required"
  aws_version="$(aws --version 2>&1)"
  [[ "$aws_version" == aws-cli/2.* ]] || fail "AWS CLI v2 is required"
  systemctl --version >/dev/null 2>&1 || fail "systemd is required"
}

ensure_directory() {
  local path="$1"
  if [[ -e "$path" && ( ! -d "$path" || -L "$path" ) ]]; then
    fail "$path must be a real directory"
  fi
  install -d -m 0755 "$path"
}

ensure_regular_file_or_absent() {
  local path="$1"
  if [[ -e "$path" || -L "$path" ]]; then
    [[ -f "$path" && ! -L "$path" ]] || fail "$path must be a regular file"
  fi
}

secure_protected_file() {
  local path="$1"
  chmod 0600 "$path"
  if [[ "$test_mode" != true ]]; then
    chown root:root "$path"
  fi
}

pending_temp=""
cleanup() {
  if [[ -n "$pending_temp" && -e "$pending_temp" ]]; then
    rm -f -- "$pending_temp"
  fi
}
trap cleanup EXIT

install_master_key_if_absent() {
  local target="$etc_dir/master.key"

  ensure_regular_file_or_absent "$target"
  if [[ ! -e "$target" ]]; then
    pending_temp="$(mktemp "$etc_dir/.master.key.XXXXXX")"
    chmod 0600 "$pending_temp"
    openssl rand -base64 32 >"$pending_temp"
    chmod 0600 "$pending_temp"
    mv "$pending_temp" "$target"
    pending_temp=""
  fi
  secure_protected_file "$target"
}

copy_env_skeleton() {
  local destination="$1"
  cp "$env_template" "$destination"
}

render_env_with_workspace_hash() {
  local destination="$1"
  local workspace_hash="$2"
  local line
  local replacements=0

  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == WORKSPACE_ACCESS_KEY_HASH=* ]]; then
      printf 'WORKSPACE_ACCESS_KEY_HASH=%s\n' "$workspace_hash"
      replacements=$((replacements + 1))
    else
      printf '%s\n' "$line"
    fi
  done <"$env_template" >"$destination"

  [[ "$replacements" == "1" ]] || fail "environment template must contain one Workspace hash"
}

prompt_and_hash_workspace_key() {
  local workspace_key
  local workspace_hash

  docker compose --project-directory "$repo_root" \
    --env-file "$env_template" build api >&2

  printf 'Workspace Access Key: ' >&2
  if ! IFS= read -r -s workspace_key; then
    printf '\n' >&2
    fail "unable to read Workspace Access Key"
  fi
  printf '\n' >&2
  if [[ -z "$workspace_key" ]]; then
    fail "Workspace Access Key must not be empty"
  fi

  if ! workspace_hash="$(
    printf '%s' "$workspace_key" |
      docker compose --project-directory "$repo_root" \
        --env-file "$env_template" run --rm --no-deps -T api \
        python -c \
        'import sys; from app.core.security import hash_workspace_key; print(hash_workspace_key(sys.stdin.read()))'
  )"; then
    unset workspace_key
    fail "Workspace Access Key hashing failed"
  fi
  unset workspace_key

  if [[ "$workspace_hash" != '$argon2id$'* || "$workspace_hash" == *$'\n'* ]]; then
    fail "Workspace Access Key hashing returned an invalid result"
  fi

  printf '%s' "$workspace_hash"
  unset workspace_hash
}

install_app_env_if_absent() {
  local target="$etc_dir/app.env"
  local workspace_hash=""

  ensure_regular_file_or_absent "$target"
  if [[ ! -e "$target" ]]; then
    pending_temp="$(mktemp "$etc_dir/.app.env.XXXXXX")"
    chmod 0600 "$pending_temp"
    if [[ "$test_mode" == true ]]; then
      copy_env_skeleton "$pending_temp"
    else
      workspace_hash="$(prompt_and_hash_workspace_key)"
      render_env_with_workspace_hash "$pending_temp" "$workspace_hash"
      unset workspace_hash
    fi
    chmod 0600 "$pending_temp"
    mv "$pending_temp" "$target"
    pending_temp=""
  fi
  secure_protected_file "$target"
}

[[ -f "$env_template" ]] || fail "$env_template is required"
if [[ "$test_mode" != true ]]; then
  validate_production_prerequisites
fi

umask 077
ensure_directory "$etc_dir"
ensure_directory "$app_dir"
install_master_key_if_absent
install_app_env_if_absent

echo "Bootstrap complete. Review $etc_dir/app.env before deployment."
