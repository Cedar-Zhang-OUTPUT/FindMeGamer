#!/bin/sh
# Root service; credentials are read by Compose from protected env files.
set -eu
directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
destination=/var/backups/find-me-gamer-agent
: "${FMG_AGENT_BACKUP_S3:?Set the dedicated S3 backup prefix}"
case "$FMG_AGENT_BACKUP_S3" in s3://zhangyue-*/backups/agent/) ;; *) exit 2;; esac
umask 077
mkdir -p "$destination"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
dump="$destination/agent-$stamp.dump"
(set -C; docker compose -f "$directory/compose.yaml" run --rm -T backup > "$dump")
test -s "$dump"
aws s3 cp --only-show-errors "$dump" "$FMG_AGENT_BACKUP_S3" --region us-west-2
echo "Agent database backup completed: $dump (local and S3)."
