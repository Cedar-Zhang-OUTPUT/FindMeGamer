# Deployment Task 6 report

## Scope and base

- Base: `faee549ee6d55fa7a4c632bee7993306dad11465`
- Scope: isolated local production-shape Compose recovery harness only.

## TDD RED

The behavior-first shell entrypoints were added before the integration runner or
override. Both exercised the intended public one-command boundary and failed
because that production-shaped harness did not exist yet, rather than because
Docker was unavailable.

- `bash integration/tests/test_service_health.sh`
  - Exit: nonzero
  - Excerpt: `integration/run.sh: No such file or directory`
- `bash integration/tests/test_worker_recovery.sh`
  - Exit: `127`
  - Excerpt: `integration/run.sh: No such file or directory`

## GREEN and verification

### Harness architecture

- `integration/compose.integration.yaml` layers on the production Compose file;
  the rendered topology is exactly `proxy`, `api`, `worker`, `beat`, `postgres`,
  and `redis`.
- Every run validates and uses a unique
  `fmg-integration-<pid>-<random>` project, network, and five named volumes. Only
  Caddy publishes a port, bound to `127.0.0.1`; PostgreSQL and Redis publish no
  host ports.
- The cleanup trap is installed before `build`, generates a private `mktemp -d`
  env/master-key directory with mode-0600 material, and can issue `down
  --volumes --remove-orphans` only for the validated integration project.
- Steam, YouTube, DeepSeek, public-page/S3 settings all point at a supervised
  loopback fake inside the API/Worker containers. SMTP is fail-closed and no
  Outreach task is created. The only credentials are obvious isolated synthetic
  canaries; no production dotenv, AWS configuration, Keychain, or provider was
  read.
- The integration Worker alone uses a five-second Redis visibility timeout so a
  forced stop has a bounded redelivery. Integration Beat alone uses a 15-second
  schedule and batch size one. Production configuration remains unchanged.

### Production-shaped scenarios

Both final clean-state invocations of `bash integration/run.sh` passed:

1. `PASS: health`; `PASS: recovery`; `PASS: isolated production-shape
   integration in 68s`.
2. `PASS: health`; `PASS: recovery`; `PASS: isolated production-shape
   integration in 68s`.

Each invocation independently proved:

- PostgreSQL 17 and Redis 7 became healthy, Alembic reached
  `20260902_0005 (head)`, and all six containers were running/healthy with the
  exact integration Compose project label. FastAPI readiness succeeded through
  integration Caddy, and Worker/Beat health checks were live.
- A Creator Analyze Job submitted through the authenticated API entered the
  local YouTube fake, its Worker was forcibly stopped, the same message was
  redelivered after restart, the same Job succeeded, and SQL found exactly one
  published Creator Profile.
- A Game and two current Creator Profiles drove real screening, pairwise, and
  final-ranking stages. The Worker was stopped after one durable pairwise row
  and during the next fake call. Before restart, the public API remained
  `running`/`pending` with empty result arrays. After redelivery it published
  exactly two unique result rows; the completed creator's `pairwise-call` log
  count remained exactly one, proving checkpoint reuse.
- Recursive public-payload canaries rejected `rank`, `score`, `total_score`,
  `dimension_scores`, and `backend_order` anywhere in the final Match response.
- A deliberately due Profile produced exactly one re-analysis Job through real
  Beat, Redis, Worker, and PostgreSQL and that Job completed.
- After all Analyze/Match/Beat work completed, Worker and Beat stopped, Redis
  was flushed, both restarted, and decoded API snapshots for all
  three Profiles, the original Analyze Job, Match Task, and complete Match
  results remained unchanged.
- Fake logs contained the expected YouTube, Steam, DeepSeek synthesis,
  screening, pairwise, ranking, and S3 calls. They contained neither the
  Workspace plaintext canary nor authorization/master-key/secret canaries.

After each final invocation, explicit Docker queries found no
`fmg-integration-*` containers, networks, or volumes. The pre-existing
`backend-postgres-test-1` and `backend-redis-test-1` containers remained healthy
and were never stopped or removed.

### Existing backend regressions

- Relevant set:
  `pytest -q tests/integration/test_analyze_vertical_slice.py
  tests/integration/test_match_checkpoint.py
  tests/integration/test_match_publication.py
  tests/unit/workers/test_schedules.py tests/integration/test_migrations.py
  tests/integration/test_match_outreach_migration.py tests/unit/test_health.py`
  -> `118 passed in 4.11s`.
- Complete existing backend integration directory:
  `pytest -q tests/integration` -> `561 passed, 2 skipped in 41.14s`.
  The two repository-declared skips were unchanged; no integration resource was
  shared with the Task 6 project.

### Static and safety gates

- `bash integration/run.sh --contract` ->
  `PASS: integration Compose contract`.
- `bash -n` on the runner, entrypoint, and both shell tests -> passed.
- In-memory `compile()` of all integration Python -> passed.
- Backend test image `black --check /integration/runtime` ->
  `4 files would be left unchanged`.
- `git diff --check`, exact changed-file scope, generated-artifact scan, and
  executable-mode review -> passed.
- Secret-signature scan found no static real key/private-key/token. External-host
  review found only the three canonical YouTube/Steam input URLs; all configured
  provider endpoints are loopback fakes. Docker/destructive scan found only the
  validated project-scoped Compose cleanup and the exact mktemp directory
  removal. No AWS, SSH, systemd, macOS, signing, real provider, or production
  resource command ran.

## Self-review and concerns

- A Docker Desktop refinement showed that marking the sole network `internal`
  prevents its loopback-published Caddy port from being reachable on the host.
  That non-required flag was removed; external boundaries remain deterministic
  local fakes through their explicit endpoint configuration, and the two final
  runs validate every exercised fake call.
- The short Celery visibility timeout and Beat interval are integration-only
  controls required to keep waits bounded. They do not alter production Worker
  recovery or the production 900-second schedule.
- No binding concern remains.

## Fix round 1 — bounded resource cleanup

### TDD RED

At immutable implementation head
`ce9f510d8e379413de634663fc0acc6a949910b2`, two focused policy tests were
added before changing the runner/runtime:

- `bash integration/tests/test_image_cleanup_policy.sh` -> exit `1`:
  `runner lacks exact project-image cleanup`, including missing project/service
  label validation and exact `docker image rm "$image_name"`.
- `bash integration/tests/test_command_bounds.sh` -> exit `1`: the portable
  timeout helper did not exist (`Errno 2`), producing helper exit `2` instead of
  the required timeout exit `124`.

These independently reproduce the reviewed image-leak and unbounded-command
contracts without mutating Docker resources.

During timeout-helper self-review, the focused AST check was tightened to cover
the helper's own waits. It produced a further genuine exit `1` RED at
`process.wait at line 31 has no timeout`; the post-SIGKILL reap was then given a
final two-second bound.

### GREEN implementation

- Added a macOS-portable Python command wrapper that gives every Docker/Compose
  invocation an explicit class-appropriate timeout: 15 seconds for version
  detection and diagnostics, 30 seconds for config/image operations, 180
  seconds for startup/migrations/commands, 900 seconds for builds, and 60
  seconds for project teardown. It starts a separate process group, sends TERM
  and then KILL on timeout, emits only the timeout duration (never arguments or
  environment), and returns `124`. Interrupts also terminate the child group.
- Every `scenario.py` Compose and direct Docker inspection now has a five-second
  subprocess timeout. Existing HTTP calls remain ten seconds, so every
  predicate operation is bounded below its 30–150 second business deadline.
- Success and failure cleanup first performs bounded, exact-project Compose
  teardown, then examines only
  `<current-project>-{api,worker,beat}:latest`. Each tag is deleted only when its
  `com.docker.compose.project` and `com.docker.compose.service` labels exactly
  match the current validated project/service. No prune, wildcard deletion, or
  image ID deletion is used. A timeout/failure advances to the remaining exact
  resources, and a cleanup defect turns an otherwise successful run nonzero.
- The fake-backed failure regression makes build exit `42`, makes project
  teardown hang, bounds teardown at 0.2 seconds, and proves all three exact
  project image tags are still removed while no broader Docker operation is
  issued.

### Fix verification

- Focused policy suite, twice:
  - `PASS: exact integration image cleanup policy`
  - timeout probe returned `124` in 0.2 seconds;
    `PASS: Docker command bounds`
  - `PASS: failed run continues exact image cleanup after bounded down timeout`
  - `PASS: integration Compose contract`
- Current full production-shape harness passed from clean state in `72s`, then
  explicit before/after and resource scans reported:
  `PASS: current full harness leaves zero project
  images/containers/volumes/networks`. An earlier GREEN run during refinement
  also passed in `71s` with zero newly retained images.
- Relevant backend regression rerun: `118 passed in 3.48s`.
- Bash syntax and in-memory Python compile passed. Black check covered runtime
  and the Docker fake fixture. `git diff --check`, exact integration/report
  scope, secret/external-host/destructive/generated-artifact scans passed.
- Before cleanup of historical artifacts, read-only enumeration matched exactly
  33 `fmg-integration-<pid>-<random>-{api,worker,beat}:latest` tags and verified
  each tag's exact Compose project/service labels; zero candidates were
  rejected. All 33 task-created, rebuildable tags were then removed one by one
  by exact reference with 30-second per-command limits: `removed_count=33`,
  `failure_count=0`, `remaining_valid_name_count=0`. No prune or glob deletion
  ran. `backend-postgres-test-1` and `backend-redis-test-1` remained healthy,
  and integration container/network/volume scans remained empty.

### Fix concerns

- None binding. Timeouts deliberately fail closed rather than claiming success
  when Docker Desktop is unresponsive; cleanup continues best-effort across all
  exact resources and reports a nonzero result when a successful scenario could
  not be fully cleaned.
