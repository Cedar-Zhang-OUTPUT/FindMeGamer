#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bootstrap="$repo_root/ops/bootstrap_server.sh"

fail() {
  echo "bootstrap server test: $*" >&2
  exit 1
}

if [[ ! -x "$bootstrap" ]]; then
  echo "ops/bootstrap_server.sh is required and must be executable" >&2
  exit 1
fi

test_root="$(mktemp -d)"

cleanup() {
  rm -rf "$test_root"
}
trap cleanup EXIT

file_mode() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    stat -f '%Lp' "$1"
  else
    stat -c '%a' "$1"
  fi
}

etc_dir="$test_root/etc"
app_dir="$test_root/app"
first_log="$test_root/first.log"
second_log="$test_root/second.log"

FMG_ETC_DIR="$etc_dir" FMG_APP_DIR="$app_dir" \
  "$bootstrap" --test-mode >"$first_log" 2>&1

test -d "$app_dir"
test "$(file_mode "$etc_dir/master.key")" = "600"
test "$(file_mode "$etc_dir/app.env")" = "600"
cmp -s "$repo_root/.env.example" "$etc_dir/app.env"

# SecretCipher.from_file requires strict base64: 32 bytes encode to exactly
# 44 characters, without the trailing newline emitted by openssl rand.
test "$(wc -c <"$etc_dir/master.key" | tr -d ' ')" = "44" ||
  fail "master key must contain exactly 44 base64 bytes with no trailing newline"
openssl base64 -d -A -in "$etc_dir/master.key" \
  >"$test_root/decoded-master-key"
test "$(wc -c <"$test_root/decoded-master-key" | tr -d ' ')" = "32"

master_key_text="$(tr -d '\n' <"$etc_dir/master.key")"
if grep -Fq "$master_key_text" "$first_log"; then
  echo "bootstrap printed the generated master key" >&2
  exit 1
fi

printf '\nOPERATOR_MARKER=preserve-me\n' >>"$etc_dir/app.env"
cp "$etc_dir/master.key" "$test_root/master-key.before"
cp "$etc_dir/app.env" "$test_root/app-env.before"
chmod 0644 "$etc_dir/master.key" "$etc_dir/app.env"

FMG_ETC_DIR="$etc_dir" FMG_APP_DIR="$app_dir" \
  "$bootstrap" --test-mode >"$second_log" 2>&1

cmp -s "$test_root/master-key.before" "$etc_dir/master.key"
cmp -s "$test_root/app-env.before" "$etc_dir/app.env"
test "$(file_mode "$etc_dir/master.key")" = "600"
test "$(file_mode "$etc_dir/app.env")" = "600"
if grep -Fq "$master_key_text" "$second_log"; then
  echo "bootstrap printed the preserved master key" >&2
  exit 1
fi

test "$(find "$etc_dir" -maxdepth 1 -type f | wc -l | tr -d ' ')" = "2"

workspace_hash='$argon2id$v=19$m=65536,t=3,p=4$cHJvZHVjdGlvbi1zYWx0$cHJvZHVjdGlvbi1oYXNoLWJ5dGVz'
render_etc_dir="$test_root/render-etc"
render_app_dir="$test_root/render-app"
FMG_ETC_DIR="$render_etc_dir" FMG_APP_DIR="$render_app_dir" \
  FMG_TEST_WORKSPACE_HASH="$workspace_hash" \
  "$bootstrap" --test-mode >"$test_root/render.log" 2>&1
rendered_env="$render_etc_dir/app.env"

# On the fixed base, test mode copies the placeholder. Reproduce the current
# production renderer's unquoted write so the real Compose assertion catches
# the reviewed interpolation defect rather than merely a missing test hook.
if grep -Fq 'WORKSPACE_ACCESS_KEY_HASH=replace-with-generated-argon2id-hash' \
  "$rendered_env"; then
  sed "s#^WORKSPACE_ACCESS_KEY_HASH=.*#WORKSPACE_ACCESS_KEY_HASH=$workspace_hash#" \
    "$rendered_env" >"$test_root/unquoted.env"
  mv "$test_root/unquoted.env" "$rendered_env"
  chmod 0600 "$rendered_env"
fi

if ! docker compose --project-directory "$repo_root" --env-file "$rendered_env" \
  config --format json >"$test_root/rendered-compose.json" \
  2>"$test_root/rendered-compose.err"; then
  fail "real Compose could not render the generated protected environment"
fi
if ! jq -e --arg expected "$workspace_hash" '
  [.services.api, .services.worker, .services.beat] |
  all((.environment.WORKSPACE_ACCESS_KEY_HASH | gsub("\\$\\$"; "$")) == $expected)
' "$test_root/rendered-compose.json" >/dev/null; then
  fail "unquoted Workspace hash did not round-trip through real Compose"
fi
docker compose --project-directory "$repo_root" --env-file "$rendered_env" \
  config --environment >"$test_root/compose-environment.txt" \
  2>>"$test_root/rendered-compose.err"
grep -Fxq "WORKSPACE_ACCESS_KEY_HASH=$workspace_hash" \
  "$test_root/compose-environment.txt" ||
  fail "Compose interpolation environment did not preserve the Workspace hash"
grep -Fxq "WORKSPACE_ACCESS_KEY_HASH='$workspace_hash'" "$rendered_env" ||
  fail "bootstrap must serialize the Workspace hash as one single-quoted dotenv value"
! grep -Fq "$workspace_hash" "$test_root/render.log" "$test_root/rendered-compose.err"

unsafe_index=0
for unsafe_hash in \
  "${workspace_hash}'" \
  "${workspace_hash}"$'\rbroken' \
  "${workspace_hash}"$'\nbroken'; do
  unsafe_index=$((unsafe_index + 1))
  unsafe_etc_dir="$test_root/unsafe-etc-$unsafe_index"
  if FMG_ETC_DIR="$unsafe_etc_dir" \
    FMG_APP_DIR="$test_root/unsafe-app-$unsafe_index" \
    FMG_TEST_WORKSPACE_HASH="$unsafe_hash" \
    "$bootstrap" --test-mode >"$test_root/unsafe-$unsafe_index.out" \
    2>"$test_root/unsafe-$unsafe_index.err"; then
    fail "bootstrap accepted a Workspace hash unsafe for single-quoted dotenv"
  fi
  [[ ! -e "$unsafe_etc_dir/app.env" ]]
  ! grep -Fq "$workspace_hash" \
    "$test_root/unsafe-$unsafe_index.out" "$test_root/unsafe-$unsafe_index.err"
done

echo "bootstrap server test: PASS"
