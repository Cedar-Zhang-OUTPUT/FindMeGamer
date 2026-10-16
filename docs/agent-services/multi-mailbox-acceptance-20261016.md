# Native multi-mailbox acceptance — 2026-10-16

This is pre-deployment acceptance on isolated native services, not a production
throughput claim or container/deployment approval. No real email, Gemini request,
production service, or Docker startup is involved.

## Environment and isolation

- Darwin 25.6.0 arm64; Python 3.13.15; Celery 5.6.3; Go 1.27.1.
- Native PostgreSQL 17.11 at `127.0.0.1:55441`, database
  `find_me_gamer_agent_test`, `max_connections=100`.
- Native Redis 8.10.1 at `127.0.0.1:55442/14`. Production specifies Redis 7:
  the native run does not establish Redis 7 or container equivalence.
- Each fixture creates a UUID PostgreSQL schema and Redis key prefix. Cleanup
  drops only its schema and deletes only keys with its prefix; no FLUSHALL.
- Two CLI configuration directories and separate tokens are created; shared-token
  cases explicitly log the second client into the first token.
- Real subprocesses run the API, dispatcher, monitor, four-slot prefork enrichment
  worker, and two two-slot prefork mailbox workers. Only external transport/model
  calls are injected by a test process factory. Production has no test URL switch.
- Mail runtime readiness is checked before explicitly releasing both persistent
  gates. The five-second send interval and ten-second dispatcher cadence remain
  in effect. The older restart-only SMTP fixture retains its documented zero
  interval; the new acceptance tests validate real pacing separately.
- Run suites sequentially: PostgreSQL advisory leadership is database-wide, so
  separate schemas do not permit independent dispatchers in the same database.

## Reproduction

From the repository root, build the CLI:

```sh
cd cli
../.local/toolchains/go1.27.1/go/bin/go build -o fmg ./cmd/fmg
cd ../agent-service
export FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test
export FMG_AGENT_TEST_REDIS_URL=redis://127.0.0.1:55442/14
export FMG_AGENT_TEST_CLI=../cli/fmg
export FMG_TASK7_RESOURCE_REPORT=/tmp/fmg-task7-resources.json
.venv/bin/pytest tests/test_multi_agent_mailboxes.py tests/test_queue_isolation_integration.py -q
.venv/bin/pytest -q
cd ..
sh cli/tests/skill_examples.sh
```

These commands require already-running isolated services. They do not start
Docker or substitute SQLite when PostgreSQL/Redis are unavailable.

## RED evidence

The API source and catalog from `3cfb566` were exported with `git archive` into
`/tmp/fmg-task7-baseline.mnhHfp`, without changing the working tree. Running the
same three dual-agent tests with
`FMG_FIXTURE_BASELINE_SRC=/tmp/fmg-task7-baseline.mnhHfp/agent-service/src` produced
**3 failed** in 13.03 seconds. Each failed on the old API's `invalid_request`
response to an explicit mailbox payload. Its `TaskInput` forbids extra fields and
has no `mailbox_id`. This proves the missing old API contract; the other fixture
roles and migrated test schema remain current, so this is not a historical load
benchmark. Full original output: `/tmp/fmg-task7-baseline-red.log`.

Harness development failures (stderr parsing, publisher queue setup, a missing
catalog in the first export, and an attempt to send an unapproved batch preview)
were corrected and are not claimed as product RED evidence. No production code
change was needed.

## Gate coverage

- Separate-token concurrent CLI creation and ownership rejection on get/start.
- Shared-token concurrent idempotency, identical IDs, changed mailbox conflict.
- Duplicate starts, duplicate broker messages, and different send keys cause at
  most one upstream call per preview.
- Same-mailbox API/batch/bounce retry starts remain at least five seconds after
  the previous call ends; bounce retry waits at least thirty seconds.
- An IPC barrier proves two mailboxes can be in transport concurrently.
- Rate limit, mailbox disablement, and bounce protection stop A while B advances.
- Four distinct Celery child PIDs enter blocked enrichment before both mailboxes
  deliver; enrichment is released only after those deliveries.
- A child exits with code 91 after simulated acceptance; stale receipt recovery
  becomes `unknown`, and redelivery does not call the provider again. The test
  expires the durable recovery timestamp instead of waiting five minutes.
- An expired broker message leaves the database recipient pending; releasing
  dispatch later completes it.
- Twenty baseline mail deliveries and twenty dual-mailbox deliveries plus twenty
  twelve-second model calls have terminal results, no duplicate send IDs, and
  empty broker queues/unacked work.

## Results and resource budget

Final frozen-code full suite: **467 passed, 1 skipped, 1 warning** in 640.12s.
The single skip is `test_local_release_image_and_restore`, which requires an
explicit locally built container image. No required PostgreSQL/Redis case was
skipped. The warning is the existing Starlette/AnyIO `BlockingPortal` deprecation.
The focused run passed **12/12**, no skips, in 531.36s; subsequent sampler and
fixture refinements were validated by the final full run, not inferred from that
earlier focused result. The CLI was rebuilt successfully with Go 1.27.1.
The complete `sh cli/tests/skill_examples.sh` passed: both offline compiled-CLI
example programs reported `passed`, followed by **4 passed, 0 skipped** in 64.12s
for the real CLI/worker restart and workspace tests (same existing warning).

Authoritative final-code measurements (`/tmp/fmg-task7-resources-final.json`):

| Measurement | Single mailbox, 20 mail | Dual mailbox, 20 mail + 20 slow enrichments |
| --- | ---: | ---: |
| Mail queue wait p95 | 190.194 s | 100.222 s |
| Mail workload elapsed | 200.260 s | 100.347 s |
| Workload peak RSS | 918,781,952 bytes (876.22 MiB) | 944,963,584 bytes (901.19 MiB) |
| Peak database connections | 13/100 | 23/100 |
| Sampled aggregate CPU peak | 222.2% | 182.8% |
| Sampled aggregate CPU mean | 12.38% | 12.32% |

There were 1,116 samples. All forty mail sends and twenty enrichment jobs reached
successful terminal results, with no duplicate send IDs. Broker queues and
unacked work drained. All six service processes and the original eight Celery
children survived; no OOM/process loss was observed. All resource assertions
passed, including dual p95 ≤ baseline+10 seconds. Dual mail is ten messages per
mailbox; model latency is twelve seconds per virtual call.
These are controlled local workload measurements, not production hardware or
provider throughput measurements.

Sampling uses native `ps` and PostgreSQL with a nominal 250 ms interval, covering
the test driver, CLI/application descendants, and dedicated PostgreSQL and Redis process trees. RSS sums
may double-count shared pages. CPU is the sum of `ps %cpu` values (process lifetime
averages), with sampled peak and mean reported. Queue wait is measured from batch
approval initiation to virtual transport start; p95 is the 19th of twenty waits.
The assertions require RSS at most 2 GiB, database connections below 70/100,
no process loss in the resource workload, and dual p95 no more than baseline+10s.

The container image/backup-restore rehearsal is an explicit separate gate. It
remains unverified here because Docker was not started. Task 8 must establish the
container, deployment, and Redis 7 boundary before deployment.

Validation logs retained locally: `/tmp/fmg-task7-focused.log`,
`/tmp/fmg-task7-full.log`, `/tmp/fmg-task7-skills.log`. The earlier focused resource
file `/tmp/fmg-task7-resources.json` has a narrower process scope; use the final
file/table above for the acceptance budget.
