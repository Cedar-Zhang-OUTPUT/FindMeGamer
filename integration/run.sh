#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:-all}"
if [[ "$mode" == "--scenario" ]]; then
  scenario="${2:-}"
  [[ "$scenario" == "health" || "$scenario" == "recovery" ]] || {
    echo "usage: bash integration/run.sh [--contract|--scenario health|--scenario recovery]" >&2
    exit 64
  }
elif [[ "$mode" != "all" && "$mode" != "--contract" ]]; then
  echo "usage: bash integration/run.sh [--contract|--scenario health|--scenario recovery]" >&2
  exit 64
fi

command -v docker >/dev/null || { echo "docker is required" >&2; exit 69; }
docker compose version >/dev/null || { echo "docker compose is required" >&2; exit 69; }

umask 077
run_dir="$(mktemp -d "${TMPDIR:-/tmp}/fmg-integration.XXXXXX")"
project_suffix="$(printf '%s' "$$-${RANDOM}" | tr -cd '0-9-')"
export FMG_INTEGRATION_PROJECT="fmg-integration-${project_suffix}"
[[ "$FMG_INTEGRATION_PROJECT" =~ ^fmg-integration-[0-9]+-[0-9]+$ ]] || {
  echo "refusing invalid integration project name" >&2
  exit 70
}
export FMG_INTEGRATION_MASTER_KEY="${run_dir}/master.key"
export FMG_COMPOSE_ENV_FILE="${run_dir}/compose.env"
export FMG_INTEGRATION_HTTP_PORT="$((20000 + RANDOM % 20000))"
backend_octet="$((24 + RANDOM % 7))"
backend_subnet="172.${backend_octet}.$((RANDOM % 200)).0/24"

cleanup() {
  cleanup_status=$?
  trap - EXIT INT TERM
  if [[ "$mode" != "--contract" ]]; then
    docker compose --project-name "$FMG_INTEGRATION_PROJECT" \
      --env-file "$FMG_COMPOSE_ENV_FILE" \
      -f "${repository_root}/compose.yaml" \
      -f "${repository_root}/integration/compose.integration.yaml" \
      down --volumes --remove-orphans >/dev/null 2>&1 || true
  fi
  rm -rf "$run_dir"
  exit "$cleanup_status"
}
trap cleanup EXIT INT TERM

unset POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD WORKSPACE_ACCESS_KEY_HASH \
  BACKEND_SUBNET SERVICE_DOMAIN FMG_AWS_REGION FMG_S3_BUCKET
openssl rand -base64 32 | tr -d '\n' >"$FMG_INTEGRATION_MASTER_KEY"
chmod 600 "$FMG_INTEGRATION_MASTER_KEY"

write_env() {
  local workspace_hash="$1"
  {
    printf 'POSTGRES_DB=find_me_gamer_integration\n'
    printf 'POSTGRES_USER=integration\n'
    printf 'POSTGRES_PASSWORD=synthetic-integration-postgres\n'
    printf "WORKSPACE_ACCESS_KEY_HASH='%s'\n" "$workspace_hash"
    printf 'BACKEND_SUBNET=%s\n' "$backend_subnet"
    printf 'SERVICE_DOMAIN=integration.invalid\n'
    printf 'FMG_AWS_REGION=us-east-1\n'
    printf 'FMG_S3_BUCKET=fmg-integration-artifacts\n'
    printf 'FMG_INTEGRATION_PROJECT=%s\n' "$FMG_INTEGRATION_PROJECT"
    printf 'FMG_INTEGRATION_MASTER_KEY=%s\n' "$FMG_INTEGRATION_MASTER_KEY"
    printf 'FMG_INTEGRATION_HTTP_PORT=%s\n' "$FMG_INTEGRATION_HTTP_PORT"
  } >"$FMG_COMPOSE_ENV_FILE"
  chmod 600 "$FMG_COMPOSE_ENV_FILE"
}

placeholder_hash='$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHRzYWx0c2FsdA$YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE'
write_env "$placeholder_hash"

compose=(
  docker compose --project-name "$FMG_INTEGRATION_PROJECT"
  --env-file "$FMG_COMPOSE_ENV_FILE"
  -f "${repository_root}/compose.yaml"
  -f "${repository_root}/integration/compose.integration.yaml"
)

contract_config="$run_dir/config.json"
"${compose[@]}" config --format json >"$contract_config"
python3 - "$contract_config" "$FMG_INTEGRATION_PROJECT" "$FMG_INTEGRATION_HTTP_PORT" <<'PY'
import json, sys
config = json.load(open(sys.argv[1], encoding="utf-8"))
project, port = sys.argv[2:]
assert set(config["services"]) == {"proxy", "api", "worker", "beat", "postgres", "redis"}
assert config["networks"]["backend"]["name"] == f"{project}-backend"
for name in ("postgres_data", "redis_data", "caddy_data", "caddy_config", "fake_state"):
    assert config["volumes"][name]["name"] == f"{project}-{name.replace('_', '-')}"
assert not config["services"]["postgres"].get("ports")
assert not config["services"]["redis"].get("ports")
ports = config["services"]["proxy"]["ports"]
assert ports == [{"mode": "ingress", "target": 8080, "published": port, "protocol": "tcp", "host_ip": "127.0.0.1"}], ports
PY

if [[ "$mode" == "--contract" ]]; then
  echo "PASS: integration Compose contract"
  exit 0
fi

started_at=$SECONDS
"${compose[@]}" build api worker beat
workspace_hash="$("${compose[@]}" run --rm --no-deps --entrypoint python api -c \
  'from app.core.security import hash_workspace_key; print(hash_workspace_key("integration-workspace-key"))')"
[[ "$workspace_hash" == '$argon2id$'* ]] || { echo "failed to generate synthetic workspace hash" >&2; exit 1; }
write_env "$workspace_hash"

diagnostics() {
  echo "integration failure diagnostics (${FMG_INTEGRATION_PROJECT})" >&2
  "${compose[@]}" ps >&2 || true
  for service in proxy api worker beat postgres redis; do
    "${compose[@]}" logs --tail 40 "$service" >&2 || true
  done
}
trap 'diagnostics' ERR

"${compose[@]}" up -d --wait --wait-timeout 60 postgres redis
"${compose[@]}" run --rm --no-deps api alembic upgrade head
"${compose[@]}" run --rm --no-deps api alembic current | grep -F '(head)'
"${compose[@]}" up -d proxy api worker beat postgres redis

export FMG_INTEGRATION_ACTIVE=1
if [[ "$mode" == "--scenario" ]]; then
  if [[ "$scenario" == "health" ]]; then
    bash "${repository_root}/integration/tests/test_service_health.sh"
  else
    bash "${repository_root}/integration/tests/test_worker_recovery.sh"
  fi
else
  bash "${repository_root}/integration/tests/test_service_health.sh"
  bash "${repository_root}/integration/tests/test_worker_recovery.sh"
fi

trap - ERR
echo "PASS: isolated production-shape integration in $((SECONDS - started_at))s"
