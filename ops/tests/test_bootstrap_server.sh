#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bootstrap="$repo_root/ops/bootstrap_server.sh"

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

echo "bootstrap server test: PASS"
