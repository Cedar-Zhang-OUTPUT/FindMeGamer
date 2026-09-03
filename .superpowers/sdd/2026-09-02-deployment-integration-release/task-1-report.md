# Deployment Task 1 Implementer Report

## Baseline and scope

- Immutable base: `b6c087bdf18d59252e6a7c05eb07f12e14e029d5`.
- `HEAD` matched the base and the worktree was clean before the first edit.
- Created only `compose.yaml`, `Caddyfile`, `.env.example`,
  `ops/tests/test_compose_config.sh`, and this required report.
- No stack was started, no AWS command or AWS resource was accessed, and no
  backend, macOS, dependency, or generated file was changed.

## Strict TDD evidence

`ops/tests/test_compose_config.sh` was created before production configuration.
Its first execution exposed that Compose checks the absent env file before the
absent Compose file. The test harness was corrected, still before production
code, to name its intended failure explicitly. The genuine RED was then:

```text
$ bash ops/tests/test_compose_config.sh
compose.yaml is required
```

The command exited 1 because the production Compose topology did not exist.
After the minimal implementation and final formatting, the focused validation
ran twice consecutively with exit 0; each run passed all 15 topology and routing
assertions.

## Implementation

- The production project contains exactly `proxy`, `api`, `worker`, `beat`,
  `postgres`, and `redis`.
- API, Worker, and Beat build from `backend/Dockerfile`. API runs
  `python -m app.run`; Worker uses
  `app.workers.celery_app:celery_app` with concurrency 5; Beat uses the same
  Celery app.
- PostgreSQL 17 and Redis 7 use pinned-major Alpine tags. PostgreSQL uses the
  stable named volume `find-me-gamer-postgres-data`; normal Docker storage on
  the EC2 host is EBS-backed. Redis and both Caddy state directories are also
  persistent named volumes.
- Only Caddy publishes host TCP ports 80 and 443. Every service joins the
  private user-defined `backend` bridge without `internal: true`, preserving
  required outbound provider, S3, and Instance Metadata access.
- API and Worker receive the root-owned host master-key path through an exact
  read-only bind mount. `.env.example` contains only inert `.invalid` or
  replace-before-deploy values; EC2 instance-role credentials are not placed in
  the file.
- All six services have health checks, `restart: unless-stopped`, and exact
  `json-file` rotation (`10m`, five files). Health-gated dependencies protect
  database/broker/API startup ordering.
- Caddy persists certificate state, enables automatic HTTPS and HTTP-to-HTTPS
  redirect, limits upstream routing to `/api/*`, `/r/*`, `/health/live`, and
  `/health/ready`, applies conservative response headers, and marks proxied
  responses `Cache-Control: no-store`.

## Verification

- Focused configuration test: 15/15 checks passed, twice consecutively after
  the final configuration edit.
- Exact brief gate passed:
  `bash ops/tests/test_compose_config.sh && docker compose --env-file .env.example config --quiet && docker run --rm -v "$PWD/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2-alpine caddy validate --config /etc/caddy/Caddyfile`.
- Official Caddy validation reported `Valid configuration`, automatic TLS, and
  enabled automatic HTTP-to-HTTPS redirects, with no formatter warning.
- `bash -n ops/tests/test_compose_config.sh`: exit 0.
- `docker compose --env-file .env.example config --quiet`: exit 0.
- `git diff --check`, exact file-scope, executable-mode, credential/certificate
  pattern, tracked-artifact, service-count, host-port, network, volume, and
  dependency checks passed.
- Self-review confirmed no extra runtime service, no non-proxy published port,
  no internal network isolation that would block egress, no plaintext secret,
  and no stack/AWS execution.

The commit subject is exactly `ops: define production compose stack`. The final
immutable hash is supplied in the post-commit handoff because embedding a
commit's own hash in its contents would change that hash.

## Concerns

Docker Hub returned transient EOF errors while fetching the official
`caddy:2-alpine` manifest through the local Docker daemon. The same official
image digest (`sha256:5f5c8640aae01df9654968d946d8f1a56c497f1dd5c5cda4cf95ab7c14d58648`)
was fetched through the public Docker mirror, locally tagged with the required
name, and the exact validation command then passed. This affected only the
local validation image pull; it did not change repository configuration or
touch AWS.
