# FMG Agent Service

Independent company API gateway. This package does not start or import the old desktop backend. At the first development checkpoint it provides health, access-token authentication and migrations only; platform and email endpoints follow in subsequent tasks.

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

## Tests

```sh
FMG_AGENT_TEST_DATABASE_URL='postgresql+psycopg://fmg_agent_test:local-test-only@127.0.0.1:55439/find_me_gamer_agent_test' .venv/bin/pytest -q
.venv/bin/black --check src tests migrations
.venv/bin/pip check
```

The PostgreSQL test creates a uniquely named schema in `find_me_gamer_agent_test`, applies migrations twice, checks actual authentication/revocation and removes only that schema. Without the test URL this one integration test is explicitly skipped. It is required for release acceptance.

Use `docker compose -f compose.test.yaml stop postgres` to stop this dedicated test container. Do not run old product Compose commands. No test needs company credentials or sends real email.

Known non-blocking dependency notice: Starlette 0.46.2 emits a deprecation warning for the AnyIO BlockingPortal alias during tests. This does not affect the production API and is tracked for a future framework upgrade, not hidden by disabling warnings.
