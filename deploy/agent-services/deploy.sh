#!/bin/sh
set -eu
if [ "${1:-}" != '--apply' ]; then
  echo 'Deployment is disabled by default. After approval: deploy.sh --apply --proxy-writes-blocked [--first-install] BACKUP_DIRECTORY' >&2
  exit 2
fi
shift
if [ "${1:-}" != '--proxy-writes-blocked' ]; then
  echo 'First block all proxy write methods and verify read receipts remain available.' >&2
  exit 2
fi
shift
first=false
if [ "${1:-}" = '--first-install' ]; then first=true; shift; fi
backup=${1:?Provide a fresh dedicated absolute backup directory}
case "$backup" in /*) ;; *) echo 'Use an absolute backup directory' >&2;exit 2;; esac
test "$backup" != /
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
compose() { docker compose -f "$directory/compose.yaml" "$@"; }
python=${FMG_AGENT_PYTHON:-python3}
: "${FMG_AGENT_ADMIN_ENV_FILE:?Set private host-reachable admin environment}"
: "${FMG_AGENT_MAILBOXES_HOST_FILE:?Set private mailbox registry path}"
compose config --quiet
umask 077
# Every attempt retains its own recoverable snapshot; never overwrite a backup.
mkdir "$backup"
cp "$FMG_AGENT_ENV_FILE" "$backup/service.env"
cp "$FMG_AGENT_PG_ENV_FILE" "$backup/postgres.env"
cp "$FMG_AGENT_ADMIN_ENV_FILE" "$backup/admin.env"
cp "$FMG_AGENT_MAILBOXES_HOST_FILE" "$backup/mailboxes.json"
cp "$directory/compose.yaml" "$backup/compose.yaml"
compose ps --all --format json > "$backup/containers-before.json"
containers=$(compose ps --status running --quiet)
if [ -n "$containers" ]; then
  docker inspect $containers > "$backup/container-inspect-before.json"
  # A TERM exit must not be immediately resurrected by unless-stopped.
  docker update --restart=no $containers >/dev/null
fi
# SIGTERM requests warm shutdown, with NO timeout kill. Legacy embedded
# dispatcher/monitor threads exit with their owning old process.
running=$(compose ps --status running --services)
if [ -n "$running" ]; then
  compose kill --signal SIGTERM $running
fi
waited=0
while [ -n "$(compose ps --status running --services)" ]; do
  if [ "$waited" -ge "${FMG_AGENT_DRAIN_SECONDS:-620}" ]; then
    compose ps --all --format json > "$backup/drain-incomplete.json"
    echo 'Warm drain incomplete. Deployment stopped; no process was force-killed. Keep proxy writes blocked and obtain operator review.' >&2
    exit 1
  fi
  sleep 2
  waited=$((waited + 2))
done
if [ "$first" = false ]; then
  (set -C; compose run --rm -T backup > "$backup/database.dump")
  test -s "$backup/database.dump"
fi
compose run --rm -T migrate
"$python" "$directory/mail_runtime.py" hold
"$python" "$directory/mail_runtime.py" check-cutover
"$python" "$directory/mailbox_preflight.py" --apply --quiescent > "$backup/identity.json"
"$python" "$directory/queue_cutover.py" audit --manifest "$backup/queues.json" > "$backup/queue-audit.json"
"$python" "$directory/queue_cutover.py" migrate --manifest "$backup/queues.json" --confirm > "$backup/queue-migration.json"
# First rollout starts only the existing mailbox. A second mailbox requires
# separate configuration, authorization and profile activation.
compose up -d --force-recreate api worker mail-worker dispatch monitor
attempt=0
until "$python" "$directory/mail_runtime.py" readiness; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 15 ]; then
    echo 'Readiness failed; gates remain held. Keep proxy writes blocked.' >&2
    exit 1
  fi
  sleep 2
done
compose ps
echo 'Local readiness passed with gates held. Proxy switch and release require the approved cutover window. No approval or SenderSafety state was reset.'
