# FMG Agent Service

Independent company API gateway. This package does not start or import the old desktop backend. It provides health, access-token authentication, migrations and catalog-driven platform read endpoints. Email endpoints and the CLI follow in subsequent tasks. It is not yet deployed as the public CLI service.

## Local setup

Run inside `agent-service` using Python 3.13:

```sh
python3.13 -m venv .venv
.venv/bin/pip install -c constraints.txt -e '.[dev]'
docker compose -f compose.test.yaml up -d --wait postgres
export FMG_AGENT_DATABASE_URL='postgresql+psycopg://fmg_agent_test:local-test-only@127.0.0.1:55439/find_me_gamer_agent_test'
.venv/bin/alembic upgrade head
.venv/bin/uvicorn fmg_agent.app:create_app --factory --host 127.0.0.1 --port 8017
```

The password above is exclusively for the local disposable test container. Production configuration must come from the private service environment, not this example or a legacy `.env` file. PostgreSQL URLs must name `find_me_gamer_agent` or `find_me_gamer_agent_test`; other databases are rejected before connection. File-backed SQLite is supported for fast local unit tests only.

## Token administration

Run on the server (or local test environment) with the new database configured:

```sh
.venv/bin/python -m fmg_agent.admin token create --label colleague-name
.venv/bin/python -m fmg_agent.admin token create --label mail-agent --scope read --scope email:enrich --scope email:send
.venv/bin/python -m fmg_agent.admin token revoke TOKEN_ID
```

Creation prints JSON containing `id` and the one-time `token` secret. Capture it privately and deliver it via an approved secure channel; never paste it into Git, shared logs or shell command arguments. Only its SHA256 digest is stored. Default scope is `read`; email enrichment/sending require explicit scopes. Revocation takes effect on the next request. There is no API for public token issuance.

`GET /v1/auth/check` requires `Authorization: Bearer …` and returns token ID, label and scopes, never the secret. Use HTTPS for remote requests. The local loopback server is a development-only HTTP exception. `/v1/health` checks database connectivity without calling any platform or model.

## Provider reads

Server-only environment variables: `FMG_AGENT_YOUTUBE_API_KEY`, `FMG_AGENT_X_BEARER_TOKEN`, optional `FMG_AGENT_STEAM_API_KEY`. Keep them in a private environment file, not command arguments. `FMG_AGENT_CATALOG_DIR` can point to the packaged `api-catalog` directory when running outside the source tree.

With a read-scoped access token, the gateway exposes:

- `GET /v1/providers/{youtube|x|steam}/operations` — compact operation inventory.
- `GET /v1/providers/{provider}/operations/{operation}` — parameters and reachable response definitions.
- `POST /v1/providers/{provider}/call` with `{"operation":"search.list","params":{"part":"snippet","q":"indie"}}` for YouTube, or the corresponding operation ID for other providers.

The server performs one request and preserves the upstream JSON under `data`. Inspect `meta.next_cursor` and `meta.rate_limit` before deciding whether to request another page. `api-catalog/coverage.md` records scope/authorization limitations. No account-private OAuth or platform write operations are silently enabled by the company key.

## Tests

```sh
FMG_AGENT_TEST_DATABASE_URL='postgresql+psycopg://fmg_agent_test:local-test-only@127.0.0.1:55439/find_me_gamer_agent_test' .venv/bin/pytest -q
.venv/bin/black --check src tests migrations
.venv/bin/pip check
```

The PostgreSQL test creates a uniquely named schema in `find_me_gamer_agent_test`, applies migrations twice, checks actual authentication/revocation and removes only that schema. Without the test URL this one integration test is explicitly skipped. It is required for release acceptance.

Use `docker compose -f compose.test.yaml stop postgres` to stop this dedicated test container. Do not run old product Compose commands. No test needs company credentials or sends real email.

Known non-blocking dependency notice: Starlette 0.46.2 emits a deprecation warning for the AnyIO BlockingPortal alias during tests. This does not affect the production API and is tracked for a future framework upgrade, not hidden by disabling warnings.
# Email enrichment worker (local development checkpoint)

The independent email routes require `email:enrich`: POST `/v1/email/enrich` with `Idempotency-Key`, GET `/v1/email/jobs/{id}`, POST `/v1/email/jobs/{id}/retry`. They operate only on the agent database, with the `0002_email_jobs` migration applied.

Set `FMG_AGENT_GEMINI_API_KEY` and `FMG_AGENT_GEMINI_MODEL` privately on the server. There is deliberately no guessed default model: use the company's verified configured model. Set `FMG_AGENT_BROKER_URL` to the company Redis connection. Never provide these credentials to CLI users.

Run `.venv/bin/python -m fmg_agent.worker`. The worker consumes only `fmg_agent`, uses the Redis key prefix `fmg_agent:`, and contains a small periodic dispatcher: no old Worker or Beat is started. Pending DB rows survive broker failures. Duplicate queue deliveries cannot claim the same running job. A 15-minute expired lease becomes an explicit retryable failure instead of automatically repeating uncertain paid work. Production prefork execution has a 10-minute hard limit; tests use solo workers with bounded external fixtures.

Public pages are fetched with validated/pinned DNS addresses and bounded redirects/content/time. At most two explicitly linked contact-like URLs are followed. Public-page business contact extraction precedes Gemini search. Failed stages are not treated as successful checkpoints; model-reported emails include public source URLs but are not claimed independently verified or deliverable.

`FMG_AGENT_EMAIL_RETENTION_DAYS` defaults to 30 (1–30 allowed). Cleanup only removes terminal new-service email jobs. Persist required results locally before expiry; idempotency keys expire with their records. No old product data is cleaned.

For the compiled-CLI/real-HTTP/PostgreSQL/Redis/restarted-Worker test, start the isolated compose services, build `../cli/fmg`, then run:

```sh
FMG_AGENT_TEST_DATABASE_URL='postgresql+psycopg://fmg_agent_test:local-test-only@127.0.0.1:55439/find_me_gamer_agent_test' FMG_AGENT_TEST_CLI='../cli/fmg' .venv/bin/pytest tests/test_email_e2e.py -q
```

Only external pages/model data are simulated in this test. No paid Gemini smoke or real email delivery has been performed for this checkpoint. This is not a deployment announcement.
