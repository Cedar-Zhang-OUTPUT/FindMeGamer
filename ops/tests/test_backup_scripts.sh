#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
backup_script="$repo_root/ops/backup_postgres.sh"
restore_script="$repo_root/ops/restore_rehearsal.sh"
service_unit="$repo_root/ops/systemd/find-me-gamer-backup.service"
timer_unit="$repo_root/ops/systemd/find-me-gamer-backup.timer"

fail() {
  echo "backup scripts test: $*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  grep -Fq -- "$needle" <<<"$haystack" || fail "missing expected text: $needle"
}

line_for() {
  local haystack="$1"
  local needle="$2"
  grep -nF -- "$needle" <<<"$haystack" | head -n 1 | cut -d: -f1
}

assert_before() {
  local haystack="$1"
  local first="$2"
  local second="$3"
  local first_line
  local second_line
  first_line="$(line_for "$haystack" "$first")"
  second_line="$(line_for "$haystack" "$second")"
  [[ -n "$first_line" && -n "$second_line" && "$first_line" -lt "$second_line" ]] ||
    fail "expected '$first' before '$second'"
}

common_environment=(
  FMG_S3_BUCKET=demo-backup-bucket
  FMG_AWS_REGION=us-west-2
  FMG_BACKUP_PREFIX=database/backups/
)

test_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "$test_root"
}
trap cleanup EXIT

backup_plan="$(
  env "${common_environment[@]}" \
    FMG_DRY_RUN=1 \
    FMG_DRY_RUN_TIMESTAMP=20260903T010203Z \
    FMG_DRY_RUN_COMMIT=0123456789ab \
    "$backup_script" --pre-migration
)"
assert_contains "$backup_plan" "pg_dump --format=custom --no-owner --no-acl"
assert_contains "$backup_plan" "pre-migration.dump"
assert_contains "$backup_plan" "aws s3 cp"
assert_contains "$backup_plan" "--sse AES256 --region us-west-2"
[[ "$(grep -cF 'aws s3 cp' <<<"$backup_plan")" = "2" ]] ||
  fail "backup plan must contain exactly two uploads"
assert_before "$backup_plan" "pg_dump --format=custom" "sha256sum-or-shasum"
assert_before "$backup_plan" "sha256sum-or-shasum" "aws s3 cp"

restore_uri="s3://demo-backup-bucket/database/backups/test.dump"
restore_plan="$(
  env "${common_environment[@]}" FMG_DRY_RUN=1 \
    "$restore_script" "$restore_uri"
)"
assert_contains "$restore_plan" "aws s3 cp"
assert_contains "$restore_plan" "test.dump.sha256"
assert_contains "$restore_plan" "find_me_gamer_restore_test"
assert_contains "$restore_plan" "pg_restore"
for table in \
  game_profiles creator_profiles analysis_jobs match_tasks outreach_campaigns deliveries; do
  assert_contains "$restore_plan" "SELECT count(*) FROM $table;"
done
assert_before "$restore_plan" "test.dump.sha256" "sha256sum-or-shasum"
assert_before "$restore_plan" "sha256sum-or-shasum" "CREATE DATABASE"
assert_before "$restore_plan" "CREATE DATABASE" "pg_restore"
assert_before "$restore_plan" "pg_restore" "SELECT version_num FROM alembic_version;"
assert_before "$restore_plan" "SELECT version_num FROM alembic_version;" "DROP DATABASE"
if grep -Fq 'DROP DATABASE IF EXISTS "find_me_gamer"' <<<"$restore_plan"; then
  fail "restore plan may not drop the production database"
fi

failure_plan="$test_root/failure-plan"
if env "${common_environment[@]}" \
  FMG_DRY_RUN=1 \
  FMG_DRY_RUN_FAIL_AFTER_CREATE=1 \
  "$restore_script" "$restore_uri" >"$failure_plan" 2>&1; then
  fail "simulated restore failure unexpectedly succeeded"
fi
assert_contains "$(<"$failure_plan")" 'DROP DATABASE IF EXISTS "find_me_gamer_restore_test";'

if env "${common_environment[@]}" FMG_DRY_RUN=1 "$backup_script" --unexpected \
  >/dev/null 2>&1; then
  fail "backup accepted an unsupported argument"
fi
if env FMG_DRY_RUN=1 FMG_S3_BUCKET=demo-backup-bucket \
  FMG_AWS_REGION=us-west-2 FMG_BACKUP_PREFIX=database/backups \
  "$backup_script" >/dev/null 2>&1; then
  fail "backup accepted a prefix without a trailing slash"
fi
if env "${common_environment[@]}" FMG_DRY_RUN=1 \
  "$restore_script" s3://other-bucket/database/backups/test.dump >/dev/null 2>&1; then
  fail "restore accepted an object outside the configured bucket"
fi

fake_bin="$test_root/bin"
fake_log="$test_root/commands.log"
fake_sources="$test_root/sources.log"
fake_aws_count="$test_root/aws-count"
mkdir -p "$fake_bin"
: >"$fake_log"
: >"$fake_sources"

cat >"$fake_bin/date" <<'EOF'
#!/usr/bin/env bash
printf '20260903T010203Z\n'
EOF

cat >"$fake_bin/git" <<'EOF'
#!/usr/bin/env bash
printf '0123456789ab\n'
EOF

cat >"$fake_bin/sha256sum" <<'EOF'
#!/usr/bin/env bash
printf 'sha256sum %s\n' "$1" >>"$FMG_FAKE_LOG"
/usr/bin/shasum -a 256 "$1"
EOF

cat >"$fake_bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'aws %s\n' "$*" >>"$FMG_FAKE_LOG"
if [[ "$3" == s3://* ]]; then
  if [[ "$3" == *.sha256 ]]; then
    digest="$(/usr/bin/shasum -a 256 "${4%.sha256}" | /usr/bin/awk '{print $1}')"
    printf '%s\n' "$digest" >"$4"
  else
    printf 'deterministic custom dump payload\n' >"$4"
  fi
  exit 0
fi
[[ -f "$3" ]] || exit 91
printf '%s\n' "$3" >>"$FMG_FAKE_SOURCES"
count=0
if [[ -f "$FMG_FAKE_AWS_COUNT" ]]; then
  count="$(<"$FMG_FAKE_AWS_COUNT")"
fi
count=$((count + 1))
printf '%s\n' "$count" >"$FMG_FAKE_AWS_COUNT"
if [[ "${FMG_FAKE_AWS_FAIL_CALL:-}" == "$count" ]]; then
  exit 92
fi
EOF

cat >"$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >>"$FMG_FAKE_LOG"
command_line=" $* "
case "$command_line" in
  *' pg_dump '*)
    printf 'deterministic custom dump payload\n'
    ;;
  *' pg_restore '*)
    /bin/cat >/dev/null
    [[ "${FMG_FAKE_RESTORE_FAIL:-}" != "1" ]] || exit 93
    ;;
  *' alembic heads '*)
    printf '20260902_0005 (head)\n'
    ;;
  *'SELECT version_num FROM alembic_version;'*)
    printf '20260902_0005\n'
    ;;
  *'SELECT count(*) FROM '*)
    printf '0\n'
    ;;
esac
EOF

chmod +x "$fake_bin/date" "$fake_bin/git" "$fake_bin/sha256sum" \
  "$fake_bin/aws" "$fake_bin/docker"

live_environment=(
  "${common_environment[@]}"
  PATH="$fake_bin:$PATH"
  FMG_FAKE_LOG="$fake_log"
  FMG_FAKE_SOURCES="$fake_sources"
  FMG_FAKE_AWS_COUNT="$fake_aws_count"
)

backup_stdout="$test_root/backup.stdout"
backup_stderr="$test_root/backup.stderr"
env "${live_environment[@]}" "$backup_script" --pre-migration \
  >"$backup_stdout" 2>"$backup_stderr"
expected_uri="s3://demo-backup-bucket/database/backups/20260903T010203Z-0123456789ab-pre-migration.dump"
[[ "$(<"$backup_stdout")" == "$expected_uri" ]] ||
  fail "live backup stdout was not exactly the dump URI"
[[ "$(wc -l <"$backup_stdout" | tr -d ' ')" = "1" ]] ||
  fail "live backup stdout must contain exactly one line"
[[ "$(grep -c '^aws s3 cp .* --sse AES256 --region us-west-2 --only-show-errors$' "$fake_log")" = "2" ]] ||
  fail "live backup must perform two encrypted Region-scoped uploads"
assert_before "$(<"$fake_log")" "pg_dump" "sha256sum"
assert_before "$(<"$fake_log")" "sha256sum" "aws s3 cp"
while IFS= read -r source_path; do
  [[ ! -e "$source_path" ]] || fail "backup temporary artifact was not cleaned up"
done <"$fake_sources"

: >"$fake_log"
: >"$fake_sources"
printf '0\n' >"$fake_aws_count"
failed_backup_stdout="$test_root/failed-backup.stdout"
if env "${live_environment[@]}" FMG_FAKE_AWS_FAIL_CALL=2 \
  "$backup_script" >"$failed_backup_stdout" 2>/dev/null; then
  fail "backup succeeded after a checksum upload failure"
fi
[[ ! -s "$failed_backup_stdout" ]] || fail "failed backup printed a success URI"
while IFS= read -r source_path; do
  [[ ! -e "$source_path" ]] || fail "failed backup left a temporary artifact"
done <"$fake_sources"

: >"$fake_log"
restore_stdout="$test_root/restore.stdout"
restore_stderr="$test_root/restore.stderr"
env "${live_environment[@]}" "$restore_script" "$restore_uri" \
  >"$restore_stdout" 2>"$restore_stderr"
assert_contains "$(<"$restore_stdout")" "Restore rehearsal succeeded"
live_restore_log="$(<"$fake_log")"
assert_before "$live_restore_log" "test.dump.sha256" "sha256sum"
assert_before "$live_restore_log" "sha256sum" "CREATE DATABASE"
assert_before "$live_restore_log" "CREATE DATABASE" "pg_restore"
assert_before "$live_restore_log" "pg_restore" "SELECT version_num FROM alembic_version;"
assert_before "$live_restore_log" "SELECT version_num FROM alembic_version;" "DROP DATABASE"
[[ "$(grep -c 'DROP DATABASE IF EXISTS \"find_me_gamer_restore_test\";' "$fake_log")" = "1" ]] ||
  fail "successful rehearsal must drop the isolated database exactly once"
if grep -q 'DROP DATABASE IF EXISTS \"find_me_gamer\";' "$fake_log"; then
  fail "live restore attempted to drop production"
fi

: >"$fake_log"
failed_restore_stdout="$test_root/failed-restore.stdout"
if env "${live_environment[@]}" FMG_FAKE_RESTORE_FAIL=1 \
  "$restore_script" "$restore_uri" >"$failed_restore_stdout" 2>/dev/null; then
  fail "restore unexpectedly succeeded after pg_restore failure"
fi
[[ ! -s "$failed_restore_stdout" ]] || fail "failed restore reported success"
[[ "$(grep -c 'DROP DATABASE IF EXISTS \"find_me_gamer_restore_test\";' "$fake_log")" = "1" ]] ||
  fail "failed rehearsal must drop the isolated database exactly once"

grep -Fqx 'WorkingDirectory=/opt/find-me-gamer' "$service_unit" ||
  fail "backup service has the wrong working directory"
grep -Fqx 'EnvironmentFile=/etc/find-me-gamer/app.env' "$service_unit" ||
  fail "backup service does not use the protected environment"
grep -Fqx 'ExecStart=/opt/find-me-gamer/ops/backup_postgres.sh' "$service_unit" ||
  fail "backup service has the wrong entry point"
grep -Fqx 'OnCalendar=daily' "$timer_unit" || fail "backup timer is not daily"
grep -Fqx 'Persistent=true' "$timer_unit" || fail "backup timer is not persistent"
if grep -Fiq 'celery' "$service_unit" "$timer_unit"; then
  fail "backup timer must be independent of Celery"
fi

echo "backup scripts test: PASS"
