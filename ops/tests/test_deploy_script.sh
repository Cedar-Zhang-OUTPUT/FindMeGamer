#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
deploy_script="$repo_root/ops/deploy.sh"
remote_script="$repo_root/ops/deploy_remote.sh"
service_unit="$repo_root/ops/systemd/find-me-gamer.service"

fail() {
  echo "deploy script test: $*" >&2
  exit 1
}

assert_contains() {
  local path="$1"
  local expected="$2"
  grep -Fq -- "$expected" "$path" || fail "missing expected text: $expected"
}

assert_before() {
  local path="$1"
  local first="$2"
  local second="$3"
  local first_line
  local second_line
  first_line="$(grep -nF -- "$first" "$path" | head -n 1 | cut -d: -f1)"
  second_line="$(grep -nF -- "$second" "$path" | head -n 1 | cut -d: -f1)"
  [[ -n "$first_line" && -n "$second_line" && "$first_line" -lt "$second_line" ]] ||
    fail "expected '$first' before '$second'"
}

[[ -x "$deploy_script" ]] || fail "ops/deploy.sh is required and must be executable"
[[ -x "$remote_script" ]] || fail "ops/deploy_remote.sh is required and must be executable"
[[ -f "$service_unit" ]] || fail "find-me-gamer.service is required"

dry_run_output="$({ FMG_DRY_RUN=1 "$deploy_script" main; })"
dry_run_file="$(mktemp)"
printf '%s\n' "$dry_run_output" >"$dry_run_file"
assert_before "$dry_run_file" "docker compose" "backup_postgres.sh --pre-migration"
assert_contains "$dry_run_file" "git -C /opt/find-me-gamer checkout --detach <resolved-commit>"
assert_before "$dry_run_file" "backup_postgres.sh --pre-migration" "alembic upgrade head"
dry_run_migrate_line="$(grep -nF 'alembic upgrade head' "$dry_run_file" | cut -d: -f1)"
dry_run_full_up_line="$(grep -nF ' up -d' "$dry_run_file" | grep -vF ' up -d --wait' | cut -d: -f1)"
[[ -n "$dry_run_migrate_line" && -n "$dry_run_full_up_line" &&
  "$dry_run_migrate_line" -lt "$dry_run_full_up_line" ]] ||
  fail "expected migration before the single full stack up"
assert_contains "$dry_run_file" "https://\${SERVICE_DOMAIN}/health/ready"
assert_contains "$dry_run_file" "120 seconds"

test_root="$(mktemp -d)"
cleanup() {
  rm -rf -- "$test_root"
  rm -f -- "$dry_run_file"
}
trap cleanup EXIT

fake_bin="$test_root/bin"
command_log="$test_root/commands.log"
environment_log="$test_root/environment.log"
ssh_log="$test_root/ssh.log"
curl_count="$test_root/curl-count"
date_count="$test_root/date-count"
mkdir -p "$fake_bin"
: >"$command_log"
: >"$environment_log"
: >"$ssh_log"
printf '0\n' >"$curl_count"
printf '0\n' >"$date_count"

cat >"$fake_bin/flock" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'flock %s\n' "$*" >>"$FMG_FAKE_COMMAND_LOG"
[[ "${FMG_FAKE_LOCK_FAIL:-0}" != "1" ]]
EOF

cat >"$fake_bin/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'git %s\n' "$*" >>"$FMG_FAKE_COMMAND_LOG"
case " $* " in
  *' status --porcelain '*)
    [[ "${FMG_FAKE_DIRTY:-0}" != "1" ]] || printf ' M ordinary-file\n'
    ;;
  *' rev-parse --verify --quiet refs/remotes/origin/'*'^{commit} '*)
    [[ "${FMG_FAKE_MISSING_REF:-0}" != "1" ]] || exit 1
    printf '%s\n' "0123456789abcdef0123456789abcdef01234567"
    ;;
  *' rev-parse --verify --quiet '*'^{commit} '*)
    [[ "${FMG_FAKE_MISSING_REF:-0}" != "1" ]] || exit 1
    printf '%s\n' "0123456789abcdef0123456789abcdef01234567"
    ;;
  *' rev-parse --short=12 HEAD '*)
    printf '0123456789ab\n'
    ;;
  *' rev-parse HEAD '*)
    printf '%s\n' "0123456789abcdef0123456789abcdef01234567"
    ;;
esac
EOF

cat >"$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'docker %s\n' "$*" >>"$FMG_FAKE_COMMAND_LOG"
for key in BACKEND_SUBNET POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD WORKSPACE_ACCESS_KEY_HASH; do
  if printenv "$key" >/dev/null 2>&1; then
    printf 'present %s\n' "$key" >>"$FMG_FAKE_ENVIRONMENT_LOG"
  fi
done
for key in SERVICE_DOMAIN FMG_S3_BUCKET FMG_AWS_REGION FMG_BACKUP_PREFIX; do
  case "$key" in
    SERVICE_DOMAIN) expected='demo.internal.example' ;;
    FMG_S3_BUCKET) expected='company-demo-artifacts' ;;
    FMG_AWS_REGION) expected='us-west-2' ;;
    FMG_BACKUP_PREFIX) expected='database/backups/' ;;
  esac
  if [[ "${!key:-}" == "$expected" ]]; then
    printf 'protected %s\n' "$key" >>"$FMG_FAKE_ENVIRONMENT_LOG"
  else
    printf 'wrong %s\n' "$key" >>"$FMG_FAKE_ENVIRONMENT_LOG"
  fi
done
command_line=" $* "
case "$command_line" in
  *' exec -T postgres '*' pg_dump '*)
    [[ "${FMG_FAKE_BACKUP_FAIL:-0}" != "1" ]] || exit 41
    printf 'deterministic custom dump payload\n'
    ;;
  *' run --rm --no-deps -T api alembic upgrade head '*)
    [[ "${FMG_FAKE_MIGRATION_FAIL:-0}" != "1" ]] || exit 42
    ;;
  *' up -d --wait '*' postgres redis '*)
    printf 'data-services %s\n' "${FMG_FAKE_EXISTING_DATA:-0}" >>"$FMG_FAKE_COMMAND_LOG"
    ;;
esac
EOF

cat >"$fake_bin/aws" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'aws %s\n' "$*" >>"$FMG_FAKE_COMMAND_LOG"
[[ -f "$3" ]] || exit 43
EOF

cat >"$fake_bin/sha256sum" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
/usr/bin/shasum -a 256 "$1"
EOF

cat >"$fake_bin/date" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "+%s" ]]; then
  count="$(<"$FMG_FAKE_DATE_COUNT")"
  printf '%s\n' "$((1000 + count * 60))"
  printf '%s\n' "$((count + 1))" >"$FMG_FAKE_DATE_COUNT"
else
  printf '20260903T010203Z\n'
fi
EOF

cat >"$fake_bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'curl %s\n' "$*" >>"$FMG_FAKE_COMMAND_LOG"
count="$(<"$FMG_FAKE_CURL_COUNT")"
printf '%s\n' "$((count + 1))" >"$FMG_FAKE_CURL_COUNT"
[[ "${FMG_FAKE_HEALTH_FAIL:-0}" != "1" ]]
EOF

cat >"$fake_bin/sleep" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf 'sleep %s\n' "$*" >>"$FMG_FAKE_COMMAND_LOG"
EOF

cat >"$fake_bin/ssh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$#" >"$FMG_FAKE_SSH_LOG"
printf '<%s>\n' "$@" >>"$FMG_FAKE_SSH_LOG"
EOF

chmod +x "$fake_bin/flock" "$fake_bin/git" "$fake_bin/docker" \
  "$fake_bin/aws" "$fake_bin/sha256sum" "$fake_bin/date" \
  "$fake_bin/curl" "$fake_bin/sleep" "$fake_bin/ssh"

env_file="$test_root/app.env"
master_key="$test_root/master.key"
lock_file="$test_root/deploy.lock"
execution_marker="$test_root/dotenv-executed"
workspace_hash='$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA'
cat >"$env_file" <<EOF
SERVICE_DOMAIN=demo.internal.example
BACKEND_SUBNET=172.30.0.0/24
POSTGRES_DB=find_me_gamer
POSTGRES_USER=find_me_gamer
POSTGRES_PASSWORD='literal dollar \$ and spaces \$(touch $execution_marker)'
WORKSPACE_ACCESS_KEY_HASH='$workspace_hash'
FMG_S3_BUCKET=company-demo-artifacts
FMG_AWS_REGION=us-west-2
FMG_BACKUP_PREFIX=database/backups/
IGNORED_COMMAND=\$(touch "$execution_marker")
EOF
printf 'not-a-real-master-key\n' >"$master_key"
chmod 0600 "$env_file" "$master_key"

precedence_env="$test_root/compose-precedence.env"
cat >"$precedence_env" <<'EOF'
SERVICE_DOMAIN=precedence.internal.example
BACKEND_SUBNET=172.30.0.0/24
POSTGRES_DB=find_me_gamer
POSTGRES_USER=find_me_gamer
POSTGRES_PASSWORD=file-compose-password-marker
WORKSPACE_ACCESS_KEY_HASH='$argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA'
FMG_AWS_REGION=us-west-2
FMG_S3_BUCKET=company-demo-artifacts
EOF
chmod 0600 "$precedence_env"
real_compose_output="$test_root/real-compose.json"
real_compose_error="$test_root/real-compose.err"
if ! env -i PATH="$PATH" HOME="${HOME:-$test_root}" \
  POSTGRES_PASSWORD=inherited-compose-password-marker \
  docker compose --project-directory "$repo_root" --env-file "$precedence_env" \
  config --format json >"$real_compose_output" 2>"$real_compose_error"; then
  fail "real Compose precedence demonstration could not render"
fi
jq -e '
  .services.api.environment.DATABASE_URL |
  contains(":inherited-compose-password-marker@postgres:")
' "$real_compose_output" >/dev/null ||
  fail "real Compose did not demonstrate shell precedence over --env-file"

base_environment=(
  PATH="$fake_bin:/usr/bin:/bin"
  FMG_DEPLOY_TEST_MODE=1
  FMG_DEPLOY_ENV_FILE="$env_file"
  FMG_DEPLOY_MASTER_KEY_FILE="$master_key"
  FMG_DEPLOY_LOCK_FILE="$lock_file"
  FMG_FAKE_COMMAND_LOG="$command_log"
  FMG_FAKE_ENVIRONMENT_LOG="$environment_log"
  FMG_FAKE_CURL_COUNT="$curl_count"
  FMG_FAKE_DATE_COUNT="$date_count"
)

run_deploy() {
  env -i "${base_environment[@]}" \
    SERVICE_DOMAIN=inherited.invalid \
    BACKEND_SUBNET=10.99.0.0/24 \
    POSTGRES_DB=inherited_database \
    POSTGRES_USER=inherited_user \
    POSTGRES_PASSWORD=inherited-password-canary \
    WORKSPACE_ACCESS_KEY_HASH=inherited-workspace-hash-canary \
    FMG_S3_BUCKET=inherited-bucket \
    FMG_AWS_REGION=eu-central-1 \
    FMG_BACKUP_PREFIX=inherited/backups/ \
    "$deploy_script" main
}

success_output="$test_root/success.out"
success_error="$test_root/success.err"
run_deploy >"$success_output" 2>"$success_error"
[[ ! -e "$execution_marker" ]] || fail "deploy executed protected dotenv content"
! grep -Fq 'literal dollar' "$success_output" "$success_error" "$command_log"
! grep -Fq "$workspace_hash" "$success_output" "$success_error" "$command_log"
assert_contains "$command_log" "https://demo.internal.example/health/ready"
assert_contains "$success_output" \
  "s3://company-demo-artifacts/database/backups/20260903T010203Z-0123456789ab-pre-migration.dump"
! grep -Eq 'inherited\.invalid|inherited-bucket|eu-central-1|inherited/backups/' \
  "$success_output" "$success_error" "$command_log"
! grep -Eq 'inherited-password-canary|inherited-workspace-hash-canary' \
  "$success_output" "$success_error" "$command_log"
assert_before "$command_log" " build" " stop proxy api worker beat"
assert_before "$command_log" " stop proxy api worker beat" " up -d --wait"
assert_before "$command_log" " up -d --wait" " pg_dump "
assert_before "$command_log" " pg_dump " "alembic upgrade head"
success_migrate_line="$(grep -nF 'alembic upgrade head' "$command_log" | cut -d: -f1)"
success_full_up_line="$(grep -n ' up -d$' "$command_log" | cut -d: -f1)"
[[ -n "$success_migrate_line" && -n "$success_full_up_line" &&
  "$success_migrate_line" -lt "$success_full_up_line" ]] ||
  fail "expected migration before the single full stack up"
[[ "$(grep -c ' up -d$' "$command_log")" = "1" ]] ||
  fail "successful deploy must perform exactly one full stack up"
while IFS= read -r compose_command; do
  [[ "$compose_command" == *"--env-file $env_file"* ]] ||
    fail "Compose command omitted the protected env-file: $compose_command"
done < <(grep '^docker compose ' "$command_log")
if grep -q '^present ' "$environment_log"; then
  leaked_key="$(grep '^present ' "$environment_log" | head -n 1 | cut -d' ' -f2)"
  fail "inherited Compose interpolation key reached fake Docker: $leaked_key"
fi
if grep -q '^wrong ' "$environment_log"; then
  wrong_key="$(grep '^wrong ' "$environment_log" | head -n 1 | cut -d' ' -f2)"
  fail "protected non-secret value did not replace inherited value: $wrong_key"
fi
compose_invocations="$(grep -c '^docker compose ' "$command_log")"
for key in SERVICE_DOMAIN FMG_S3_BUCKET FMG_AWS_REGION FMG_BACKUP_PREFIX; do
  [[ "$(grep -c "^protected $key$" "$environment_log")" == "$compose_invocations" ]] ||
    fail "protected value was not authoritative for every Compose invocation: $key"
done
assert_contains "$success_output" "0123456789abcdef0123456789abcdef01234567"

for existing in 0 1; do
  : >"$command_log"
  printf '0\n' >"$curl_count"
  printf '0\n' >"$date_count"
  env -i "${base_environment[@]}" FMG_FAKE_EXISTING_DATA="$existing" \
    "$deploy_script" main >/dev/null 2>"$test_root/existing-$existing.err"
  assert_contains "$command_log" "data-services $existing"
  [[ "$(grep -c ' up -d$' "$command_log")" = "1" ]] ||
    fail "initial/existing deployment must full-up exactly once"
done

for failure in backup migration; do
  : >"$command_log"
  printf '0\n' >"$curl_count"
  printf '0\n' >"$date_count"
  failure_environment=()
  if [[ "$failure" == "backup" ]]; then
    failure_environment+=(FMG_FAKE_BACKUP_FAIL=1)
  else
    failure_environment+=(FMG_FAKE_MIGRATION_FAIL=1)
  fi
  if env -i "${base_environment[@]}" "${failure_environment[@]}" \
    "$deploy_script" main >"$test_root/$failure.out" 2>"$test_root/$failure.err"; then
    fail "deploy accepted a $failure failure"
  fi
  assert_contains "$command_log" " stop proxy api worker beat"
  if grep -q ' up -d$' "$command_log"; then
    fail "$failure failure restarted the application stack"
  fi
  if [[ "$failure" == "backup" ]] && grep -Fq 'alembic upgrade head' "$command_log"; then
    fail "migration ran after backup failure"
  fi
done

: >"$command_log"
printf '0\n' >"$curl_count"
printf '0\n' >"$date_count"
if env -i "${base_environment[@]}" FMG_FAKE_HEALTH_FAIL=1 \
  "$deploy_script" main >"$test_root/timeout.out" 2>"$test_root/timeout.err"; then
  fail "deploy accepted readiness timeout"
fi
[[ "$(<"$curl_count")" -le 2 ]] || fail "bounded fake readiness made too many attempts"
assert_contains "$command_log" " ps"
assert_contains "$test_root/timeout.err" "120 seconds"

for rejection in lock dirty missing-ref; do
  : >"$command_log"
  rejection_environment=()
  case "$rejection" in
    lock) rejection_environment+=(FMG_FAKE_LOCK_FAIL=1) ;;
    dirty) rejection_environment+=(FMG_FAKE_DIRTY=1) ;;
    missing-ref) rejection_environment+=(FMG_FAKE_MISSING_REF=1) ;;
  esac
  if env -i "${base_environment[@]}" "${rejection_environment[@]}" \
    "$deploy_script" main >/dev/null 2>"$test_root/$rejection.err"; then
    fail "deploy accepted $rejection condition"
  fi
  if grep -Eq '^docker compose .*(build|stop|up|run|exec)' "$command_log"; then
    fail "$rejection rejection reached a mutating Docker command"
  fi
done

: >"$command_log"
if env -i "${base_environment[@]}" "$deploy_script" 'main;touch bad' \
  >/dev/null 2>&1; then
  fail "deploy accepted an unsafe ref"
fi
[[ ! -s "$command_log" ]] || fail "unsafe ref reached an external command"

remote_environment=(PATH="$fake_bin:/usr/bin:/bin" FMG_FAKE_SSH_LOG="$ssh_log")
env -i "${remote_environment[@]}" "$remote_script" deployer@demo.internal.example release/v1
[[ "$(sed -n '1p' "$ssh_log")" = "2" ]] || fail "remote wrapper did not make one SSH invocation"
grep -Fxq '<deployer@demo.internal.example>' "$ssh_log" || fail "remote wrapper changed the host"
grep -Fxq "<cd /opt/find-me-gamer && sudo ./ops/deploy.sh 'release/v1'>" "$ssh_log" ||
  fail "remote wrapper did not send one exact quoted deploy command"
for unsafe_host in '-oProxyCommand=bad' 'bad host' 'host;bad'; do
  if env -i "${remote_environment[@]}" "$remote_script" "$unsafe_host" main \
    >/dev/null 2>&1; then
    fail "remote wrapper accepted unsafe host: $unsafe_host"
  fi
done
if env -i "${remote_environment[@]}" "$remote_script" demo.internal.example \
  'main;bad' >/dev/null 2>&1; then
  fail "remote wrapper accepted unsafe ref"
fi

grep -Fxq 'WorkingDirectory=/opt/find-me-gamer' "$service_unit" ||
  fail "service unit has the wrong working directory"
grep -Fxq 'EnvironmentFile=/etc/find-me-gamer/app.env' "$service_unit" ||
  fail "service unit does not load the protected environment"
grep -Fxq 'ExecStart=/usr/bin/docker compose --project-directory /opt/find-me-gamer --env-file /etc/find-me-gamer/app.env up -d' "$service_unit" ||
  fail "service unit has the wrong start command"
grep -Fxq 'ExecStop=/usr/bin/docker compose --project-directory /opt/find-me-gamer --env-file /etc/find-me-gamer/app.env stop' "$service_unit" ||
  fail "service unit has the wrong stop command"
if grep -Eiq 'deploy\.sh|fetch|alembic|backup_postgres|curl' "$service_unit"; then
  fail "service unit performs deployment work at boot"
fi

echo "deploy script test: PASS"
