#!/bin/sh
set -eu
server=${1:?Usage: smoke.sh HTTPS_SERVER}
case "$server" in https://*) ;; http://127.0.0.1:*) ;; *) exit 2;; esac
python3 - "$server" <<'PY'
import json, os, sys
try:
    with open(os.environ['FMG_CONFIG']) as source:
        configured = json.load(source)['server']
    if configured.rstrip('/') != sys.argv[1].rstrip('/'):
        raise ValueError()
except (KeyError, ValueError, OSError):
    sys.exit('Set FMG_CONFIG to a private CLI config for this exact smoke target.')
PY
curl --fail --silent --show-error --max-time 15 "$server/v1/health"
echo
"${FMG_BIN:-fmg}" auth check
"${FMG_BIN:-fmg}" steam describe store.search
"${FMG_BIN:-fmg}" email templates
echo 'Read-only configuration smoke passed. No paid provider operation or email was sent.'
