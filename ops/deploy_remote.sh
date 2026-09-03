#!/usr/bin/env bash
set -euo pipefail
if [[ "$-" == *x* ]]; then
  set +x
fi

fail() {
  echo "deploy-remote: $*" >&2
  exit 1
}

(( $# >= 1 && $# <= 2 )) || fail "usage: $0 <host> [git-ref]"
host="$1"
requested_ref="${2:-main}"

[[ "$host" =~ ^([A-Za-z0-9][A-Za-z0-9._-]*@)?[A-Za-z0-9][A-Za-z0-9.-]*$ &&
  "$host" != *'..'* && "$host" != *'.-'* && "$host" != *'-.'* ]] ||
  fail "host must be an explicit safe SSH hostname"
[[ "$requested_ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$ &&
  "$requested_ref" != *'..'* && "$requested_ref" != *'//'* &&
  "$requested_ref" != *'@{'* && "$requested_ref" != */ &&
  "$requested_ref" != *. ]] ||
  fail "git ref must use only safe branch, tag, or commit characters"
command -v ssh >/dev/null 2>&1 || fail "ssh is required"

remote_command="cd /opt/find-me-gamer && sudo ./ops/deploy.sh '$requested_ref'"
ssh "$host" "$remote_command"
