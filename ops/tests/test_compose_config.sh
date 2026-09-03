#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f compose.yaml ]]; then
  echo "compose.yaml is required" >&2
  exit 1
fi

rendered="$(docker compose --env-file .env.example config --format json)"

jq -e '.services | keys == ["api", "beat", "postgres", "proxy", "redis", "worker"]' \
  <<<"$rendered"
jq -e '.services.postgres.ports == null and .services.redis.ports == null' \
  <<<"$rendered"
jq -e '
  [.services | to_entries[] | select(.key != "proxy") | .value.ports] |
  all(. == null)
' <<<"$rendered"
jq -e '
  [.services.proxy.ports[] | .target] | sort == [80, 443]
' <<<"$rendered"
jq -e '
  [.services | to_entries[] |
    (.value.restart == "unless-stopped") and
    (.value.networks | keys == ["backend"]) and
    (.value.healthcheck != null) and
    (.value.logging.driver == "json-file") and
    (.value.logging.options."max-size" == "10m") and
    (.value.logging.options."max-file" == "5")
  ] | all
' <<<"$rendered"
jq -e '.networks.backend.internal != true' <<<"$rendered"

jq -e '.services.postgres.image == "postgres:17-alpine"' <<<"$rendered"
jq -e '.services.redis.image == "redis:7-alpine"' <<<"$rendered"
jq -e '.services.proxy.image == "caddy:2-alpine"' <<<"$rendered"
jq -e '
  [.services.api, .services.worker, .services.beat] |
  all(.build.context | endswith("/backend")) and
  all(.build.dockerfile == "Dockerfile")
' <<<"$rendered"
jq -e '
  [.services.api, .services.worker] |
  all(any(.volumes[];
    .type == "bind" and
    .source == "/etc/find-me-gamer/master.key" and
    .target == "/etc/find-me-gamer/master.key" and
    .read_only == true))
' <<<"$rendered"
jq -e '
  any(.services.postgres.volumes[];
    .type == "volume" and
    .source == "postgres_data" and
    .target == "/var/lib/postgresql/data") and
  (.volumes.postgres_data.name == "find-me-gamer-postgres-data")
' <<<"$rendered"

jq -e '.services.api.command == ["python", "-m", "app.run"]' <<<"$rendered"
jq -e '
  (.services.worker.command | tostring | contains("app.workers.celery_app:celery_app")) and
  (.services.worker.command | tostring | contains("--concurrency=5")) and
  (.services.beat.command | tostring | contains("app.workers.celery_app:celery_app")) and
  (.services.beat.command | tostring | contains("beat"))
' <<<"$rendered"
jq -e '
  (.services.api.depends_on.postgres.condition == "service_healthy") and
  (.services.api.depends_on.redis.condition == "service_healthy") and
  (.services.worker.depends_on.postgres.condition == "service_healthy") and
  (.services.worker.depends_on.redis.condition == "service_healthy") and
  (.services.beat.depends_on.postgres.condition == "service_healthy") and
  (.services.beat.depends_on.redis.condition == "service_healthy") and
  (.services.proxy.depends_on.api.condition == "service_healthy")
' <<<"$rendered"

grep -Fq '{$SERVICE_DOMAIN:localhost}' Caddyfile
grep -Fq '@backend path /api/* /r/* /health/live /health/ready' Caddyfile
grep -Fq 'reverse_proxy api:8000' Caddyfile
grep -Fq 'Cache-Control "no-store"' Caddyfile
grep -Fq 'X-Content-Type-Options "nosniff"' Caddyfile
