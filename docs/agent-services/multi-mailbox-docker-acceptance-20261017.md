# Isolated Docker acceptance — 2026-10-17

This supplements the [native acceptance](multi-mailbox-acceptance-20261016.md).
The user authorized temporary isolated Docker tests, not production deployment,
publication or external provider operations. Original FMG services remained stopped;
the unrelated running Supabase database was not changed.

## Environment

- Reviewed production source: `f35eb8f`; subsequent changes are test harness only.
- Local image: `fmg-agent:isolated-f35eb8f-20261017`, Linux/arm64,
  image ID `sha256:f372a2c0c5d862db9ee7fec198742c22fb6b80d0236d4408ea18591cc30cb454`.
- Docker Engine 29.2.1; PostgreSQL 17.11 (`postgres:17-alpine`), Redis 7.4.11
  (`redis:7-alpine`). This is not a production host/architecture capacity test.
- Dedicated `fmg-isolated-20261017` network; PostgreSQL on loopback port 55449,
  Redis on loopback port 55450, database 14. PostgreSQL test data uses temporary
  memory-backed storage. No real credentials were provided to containers.
- UUID schemas and owned container names isolate each rehearsal. No global Docker
  prune, Redis FLUSHALL, old service restart or production access was performed.

The first setup failed before database access because Docker's internal network
suppressed published ports. Only newly created empty test services/network were
recreated on a dedicated bridge with loopback-only port bindings. The default
Docker subnet pool was exhausted; the dedicated subnet was chosen after checking
existing Docker networks and host routes. These were local harness setup issues,
not product regressions.

## Actual container coverage

The opt-in `test_release_container.py` now accepts explicit local image, network
and PostgreSQL container overrides, without pulling an image automatically.
The test ran migrations twice and exercised the compiled CLI's read-only smoke,
actual Celery processing of a locally rejected private URL, non-root API user,
PostgreSQL custom-format dump and restore. Restored token/job counts and migration
version `0013_mail_runtime` were checked.

API, enrichment, mail, dispatcher and monitor ran in Linux containers under
closed runtime gates. Probes verified Linux PID/start identity, primary mail queue
with two slots, enrichment queue with four slots, and monitor `held-local` mode.
All five roles proved the host administrator's actual database/schema and Redis
target via the shared advisory-lock/nonce challenge. Both gates stayed closed;
the nonce was removed afterward. Mail/monitor stopped gracefully with exit 0
before the private-URL enrichment test opened gates. No external mail/model/OAuth
operation was requested.

An actual smoke failure (`insufficient_scope`) exposed an outdated disposable test
token: mailbox discovery requires `email:send`, alongside `read`. Only the test
token was corrected; the production endpoint and smoke contract were unchanged.
A held-role fixture initially named the mailbox `primary`; it was corrected to
the existing default ID `ontologyplay`. Final focused rehearsal: **1 passed in
31.90 seconds**. Independent scoped review approved the test-only changes with no
remaining actionable findings.

## Redis 7 regression and limits

Broad regression on `ad8d7ea`: **548 passed, 1 deselected, 1 warning in 386.60s**,
exit 0; no skips or failures. This includes the actual container rehearsal and
dual-agent/queue isolation tests. The warning is the existing Starlette/AnyIO
`BlockingPortal` deprecation, not a new regression.

From `agent-service`, with the isolated services already running:

```sh
FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test:local-test-only@127.0.0.1:55449/find_me_gamer_agent_test \
FMG_AGENT_TEST_REDIS_URL=redis://127.0.0.1:55450/14 \
FMG_AGENT_TEST_CLI=../cli/fmg \
FMG_AGENT_TEST_IMAGE=fmg-agent:isolated-f35eb8f-20261017 \
FMG_AGENT_TEST_NETWORK=fmg-isolated-20261017 \
FMG_AGENT_TEST_POSTGRES_CONTAINER=fmg-isolated-20261017-postgres \
.venv/bin/pytest -q -k 'not test_resource_budget_baseline_and_slow_enrichment' --tb=short
```

Controller terminal session `59812`, final output chunk `585f8d`, contains the
complete summary. Test credentials above are disposable local-only values.

The mixed host/container regression deliberately excludes only
`test_resource_budget_baseline_and_slow_enrichment`: its native `ps` sampler assumes
PostgreSQL/Redis PIDs share the host namespace, which Docker does not. Applying it
here would produce invalid resource accounting. The previous reviewed full native
run passed that case, with 986,316,800-byte peak RSS, 26/100 database connections,
dual-mail p95 100.231s versus 190.400s baseline, drained queues and eight surviving
worker children. Those numbers remain native virtual-provider measurements, not
Docker or production resource claims.

Fresh Go `test -count=1 ./...` and `vet ./...` passed. Both compiled CLI/Skill
example programs passed against loopback simulations. CLI/Skill candidate remains
`fmg-v0.8.0`, unpublished; no production source changed during this rehearsal.

## Cleanup and remaining boundaries

After the final run, there were no `fmg-release-*` containers and no leftover
test schemas. The two dedicated PostgreSQL/Redis containers were stopped and
removed, including the owned temporary Redis volume, and their dedicated network
was removed. Only generated test data was discarded; it contains no user data.
The local image and acceptance records remain. Original FMG containers stayed
stopped; the unrelated Supabase database stayed healthy and running. Docker
Desktop was not globally stopped.

This does not exercise the complete production proxy/cutover sequence or real
provider connectivity. Deployment script warm-drain/deadline orchestration remains
covered by deterministic command fixtures, not a production rollout. Production
preflight/window, publication and second-mailbox configuration/authorization remain
separate steps. The second mailbox is still disabled/unconfigured.
