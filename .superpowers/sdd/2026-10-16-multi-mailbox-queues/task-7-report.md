# Task 7 implementation report

Status: DONE_WITH_CONCERNS. Native required acceptance is complete; container and
Redis 7 equivalence remain the Task 8 deployment boundary. No production code,
production data, real mail/Gemini calls, or Docker startup was involved.

## Implementation

- Added `tests/mailbox_runtime_fixture.py`: unique PostgreSQL schema/Redis prefix,
  two CLI configuration directories/tokens, real API/dispatcher/monitor subprocesses,
  4-slot enrichment and two 2-slot prefork mail consumers. Only upstream mail/model
  boundaries are virtualized in the test process factory. Runtime readiness is
  checked and the persistent gates explicitly released.
- Added three dual-agent tests and nine queue/resource cases (including the
  parameterized failure cases). They exercise actual concurrent CLI processes,
  ownership, idempotency, duplicate broker messages, five-second shared pacing,
  thirty-second bounce retry, overlapping mailboxes, 429/disabled/protection
  isolation, four blocked enrichment child PIDs, real child exit after submission,
  durable unknown recovery, expired messages, and resource/queue drain budgets.
- Migrated the older worker/CLI fixtures to explicit roles, a separate dispatcher,
  explicit mailbox selection, readiness/release, and test Redis configuration.
  The legacy bounce test now restarts the mail consumer specifically. It retains
  its documented zero pacing interval; the new acceptance cases use real timing.
- Updated the opt-in container rehearsal for the new role entry point,
  dispatcher, runtime gate and current schema revision, without executing it.
- Added `docs/agent-services/multi-mailbox-acceptance-20261016.md` with reproduction,
  limitations, evidence and actual measurements.

## TDD / RED

Exported `3cfb566` API source and catalog into an isolated temporary directory:

```sh
task7_baseline=$(mktemp -d /tmp/fmg-task7-baseline.XXXXXX)
git archive 3cfb566 agent-service/src | tar -x -C "$task7_baseline"
git archive 3cfb566 api-catalog | tar -x -C /tmp/fmg-task7-baseline.mnhHfp
```

With the common isolated environment below, ran:

```sh
FMG_FIXTURE_BASELINE_SRC=/tmp/fmg-task7-baseline.mnhHfp/agent-service/src \
  .venv/bin/pytest tests/test_multi_agent_mailboxes.py -q
```

Result: **3 failed, 1 warning in 13.03s**. All three fail at the old API's
`invalid_request` response to explicit `mailbox_id`; the old `TaskInput` forbids
extra fields and lacks mailbox selection. Same acceptance tests, exported old API;
the migrated schema and other process roles remain current. This demonstrates the
missing old API contract, not a historical full-stack load benchmark.
Evidence: `/tmp/fmg-task7-baseline-red.log`.

Earlier harness failures were not product RED: missing catalog in the first
export, stderr JSON parsing, publisher default queue mismatch, and direct sending
of an unapproved batch preview. The last correctly returned `outreach_task_paused`;
the pacing fixture now creates a standalone preview. No production defect/fix was
needed. One early failed-setup UUID schema was explicitly removed afterward;
fixture teardown now also runs when initialization fails.

## GREEN commands and results

CLI rebuilt with `cd cli && ../.local/toolchains/go1.27.1/go/bin/go build -o fmg ./cmd/fmg`.

Common environment from `agent-service`:

```sh
export FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test
export FMG_AGENT_TEST_REDIS_URL=redis://127.0.0.1:55442/14
export FMG_AGENT_TEST_CLI=../cli/fmg
```

- Focused legacy validation: `.venv/bin/pytest tests/test_email_e2e.py tests/test_outreach_local.py -xq`
  — **4 passed, 1 warning in 75.95s** (`/tmp/fmg-task7-legacy.log`).
- Focused new acceptance: `FMG_TASK7_RESOURCE_REPORT=/tmp/fmg-task7-resources.json .venv/bin/pytest tests/test_multi_agent_mailboxes.py tests/test_queue_isolation_integration.py -q`
  — **12 passed, 0 skipped, 1 warning in 531.36s** (`/tmp/fmg-task7-focused.log`).
- Final frozen-code full suite: `FMG_TASK7_RESOURCE_REPORT=/tmp/fmg-task7-resources-final.json .venv/bin/pytest -q -ra`
  — **467 passed, 1 skipped, 1 warning in 640.12s** (`/tmp/fmg-task7-full.log`).
  The only skip is `test_local_release_image_and_restore`: explicit container
  image opt-in was absent, and Docker remained stopped. No required PG/Redis gate
  skipped. The sole warning is existing Starlette/AnyIO BlockingPortal deprecation.
- From repository root with the same DB/Redis environment:
  `sh cli/tests/skill_examples.sh` — both compiled-CLI example programs passed;
  subsequent real email/workspace tests **4 passed, 0 skipped, 1 warning in 64.12s**
  (`/tmp/fmg-task7-skills.log`).
- Black check on seven changed Python files and `git diff --check` passed.

The final full run covers the refinements made after the focused run loaded its
tests: separate config directories, removal of crash-cooldown confounding,
retry-specific timing, broader resource scope, sampler health and child survival.
The final JSON, not the earlier narrower-scope JSON, is authoritative.

## Actual final resource outcome

Darwin arm64, Python 3.13.15, Celery 5.6.3, PostgreSQL 17.11, Redis 8.10.1,
Go 1.27.1. Test max_connections is 100.

| Metric | Single mailbox 20 mail | Dual mailbox 20 mail + 20 slow enrichments |
| --- | ---: | ---: |
| Mail wait p95 | 190.194 s | 100.222 s |
| Mail elapsed | 200.260 s | 100.347 s |
| Peak RSS | 918,781,952 B / 876.22 MiB | 944,963,584 B / 901.19 MiB |
| Peak DB connections | 13 | 23 |
| Aggregate sampled CPU peak | 222.2% | 182.8% |
| Aggregate sampled CPU mean | 12.38% | 12.32% |

1,116 native ps/PG samples, nominal 250 ms interval. Scope includes test driver,
CLI/application descendants, PostgreSQL and Redis trees. CPU is summed ps process
lifetime percentage, not an instantaneous per-core profiler; summed RSS can
double-count shared pages. Forty mail sends and twenty enrichment jobs completed;
no duplicate send IDs, queues/unacked drained, six role processes and original
eight worker children alive. No OOM/process loss observed. All assertions passed:
RSS ≤2 GiB, DB <70%, and dual p95 ≤baseline+10s. This is a controlled local
pre-deployment budget, not production hardware or provider throughput evidence.

## Self-review and concerns

Read the complete own diff. Production configuration, pacing, retries, templates,
historical data and runtime fencing are unchanged. Test callbacks are confined to
test process factories. Cleanup uses UUID targets/own Redis keys only; no FLUSHALL.
All spawned fixture processes exited after validation. The single large fixture
file (465 lines) owns one coherent process-runtime utility; no unplanned production
refactor or file split was introduced.

The required tests must run sequentially on this DB because the dispatcher leader
lock is database-wide. Briefly overlapping preliminary legacy/new runs delayed
dispatch; the final focused/full/skill runs were sequential. Native Redis 8.10.1
does not establish compatibility with production Redis 7. Container image,
backup/restore, deployment and production resource validation remain Task 8.

Changed files: `agent-service/tests/mailbox_runtime_fixture.py`,
`test_multi_agent_mailboxes.py`, `test_queue_isolation_integration.py`,
`email_worker_fixture.py`, `test_email_e2e.py`, `test_outreach_local.py`,
`test_release_container.py`; `cli/tests/skill_examples.sh`;
`docs/agent-services/multi-mailbox-acceptance-20261016.md`; this report.
