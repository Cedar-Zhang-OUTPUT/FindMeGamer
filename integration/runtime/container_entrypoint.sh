#!/usr/bin/env bash
set -euo pipefail

python /integration/runtime/fake_external.py &
fake_pid=$!
main_pid=""

forward_signal() {
  local signal="$1"
  if [[ -n "$main_pid" ]] && kill -0 "$main_pid" 2>/dev/null; then
    kill -s "$signal" "$main_pid" 2>/dev/null || true
  fi
}

cleanup() {
  kill -TERM "$fake_pid" 2>/dev/null || true
  wait "$fake_pid" 2>/dev/null || true
}

trap 'forward_signal TERM' TERM INT
trap 'forward_signal QUIT' QUIT
trap cleanup EXIT

"$@" &
main_pid=$!
set +e
wait "$main_pid"
main_status=$?
set -e
exit "$main_status"
