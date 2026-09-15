#!/bin/sh
set -eu
if [ "${1:-}" != '--apply' ]; then
  echo 'Deployment is disabled by default. After approval: deploy.sh --apply [--first-install] BACKUP_DIRECTORY' >&2
  exit 2
fi
shift
first=false
if [ "${1:-}" = '--first-install' ]; then first=true; shift; fi
backup=${1:?Provide a dedicated absolute backup directory}
case "$backup" in /*) ;; *) echo 'Use an absolute backup directory' >&2;exit 2;; esac
test "$backup" != /
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
compose() { docker compose -f "$directory/compose.yaml" "$@"; }
compose config --quiet
# Only the NEW project is stopped; no old API, Worker or Beat is started.
compose stop api worker
umask 077
mkdir -p "$backup"
if [ "$first" = false ]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  dump="$backup/agent-$stamp.dump"
  (set -C; compose run --rm -T backup > "$dump")
  test -s "$dump"
  echo "New-service database backed up to $dump"
fi
compose run --rm -T migrate
compose up -d api worker
compose ps
echo 'Verify health and authenticated smoke before switching the HTTPS proxy. This script never changes the proxy.'
