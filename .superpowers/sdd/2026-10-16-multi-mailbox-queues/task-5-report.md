# Task 5 implementation report

Status: DONE. Implementation and final regression verified; deployment/integration boundaries are listed below.

## Delivered

- `worker_args(role, mailbox_id)` accepts enrichment (4 slots, `fmg_enrichment`) or mail (2 slots, `fmg_mail.ID`). Invalid roles/IDs/combinations fail. No worker-ready polling threads remain. Actual normal/retry Celery tasks pass their own expected mailbox ID and registry; tasks use `shared=False` to keep app closures isolated.
- `dispatch.dispatch_once(settings, sessions, publish)` calls `publish(task_name, identifier, queue)` and returns counts per enabled queue. Every 10-second loop publishes at most 20 enrichment jobs and 20 total normal/retry sends per enabled mailbox, interleaving normal and retry work. DB pending records remain durable on broker rejection.
- One PostgreSQL connection-owned advisory leader spans the dispatcher loop. Fenced sessions pin its physical backend; a guarded DB operation precedes each broker publication. Terminating that backend stops further publications. Existing monitor leader/session fencing was retained.
- Migration `0013_mail_runtime` creates one constrained row with both gates false. The common sending path holds a PostgreSQL shared row lock through pacing, reservation, transport, and receipt completion. `set_runtime` takes the exclusive row lock, so hold drains active operations. Missing runtime row/schema fails closed. Receipt replays remain readable. API, batch and retry paths return `mail_service_maintenance` without new attempts or task/retry status rewrites.
- Startup `check_readiness(settings, sessions, registry=None)` checks migration revision and runtime row, registers immutable identities, and verifies consistent completed historical backfill. It is called by worker, dispatch and monitor process entrypoints. It does not release the gates.
- Existing send pacing, transport task timeout, prefetch, JSON serialization, retention, retry budgets, unknown replay handling and approval/template contents remain unchanged.

## TDD / verification evidence

Working directory for pytest: `agent-service`. PostgreSQL runs used:

`FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test`

- Initial RED: `.venv/bin/pytest tests/test_queue_isolation.py tests/test_mail_runtime.py -q` -> 5 failed, 2 skipped. Missing worker routing interface, dispatch/runtime modules, and runtime table. This initial invocation omitted the PG environment variable; subsequent PG checks used the native DB.
- Additional RED: actual Celery task execution caught shared task closures reading another app's DB configuration (`no such table: outreach_recipients`); setting `shared=False` fixed the real app/task isolation problem. An unrelated new routing fixture initially lacked the required file-backed Settings database URL and was corrected.
- Additional RED: `... .venv/bin/pytest tests/test_queue_isolation.py::test_fenced_dispatch_persists_recovery -q` -> 1 failed (`running` instead of `failed`). Shared owner sessions had left recovery writes inside the gate transaction; explicitly committing the gate's successful transaction fixed persistence without releasing its lock during publication.
- Additional RED: `.venv/bin/pytest tests/test_mail_runtime.py::test_send_gate_blocks_api_and_worker tests/test_mail_runtime.py::test_hold_preserves_due_retry -q` -> 2 failed (`None` instead of explicit maintenance result). Workers now return the maintenance code while preserving pending/approved state.
- Core GREEN: `... .venv/bin/pytest tests/test_queue_isolation.py tests/test_mail_runtime.py tests/test_email_worker.py tests/test_send_pacing_postgres.py tests/test_deploy_tools.py -q` -> 26 passed, 1 existing Starlette deprecation warning, 14.80s.
- Full regression before final explicit-maintenance-result refinement: `... .venv/bin/pytest -q -rs` -> 448 passed, 3 skipped, 1 existing warning, 44.81s. Earlier iteration: 446 passed, 3 skipped.
- Final full regression after all changes: `FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test .venv/bin/pytest -q -rs` -> **448 passed, 3 skipped, 1 existing warning in 43.75s**.
- `git diff --check` passed. Black formatted the new/modified implementation and new tests.

The existing warning is `anyio.abc.BlockingPortal` deprecation from Starlette TestClient. Skips are `test_email_e2e.py::test_cli_email_worker_restart` (compiled CLI not supplied), `test_outreach_local.py::test_local_cli_dashboard_and_smtp` (compiled CLI not supplied), and `test_release_container.py::test_local_release_image_and_restore` (Docker release image opt-in absent). No Docker startup, real Gemini/mail/upstream call, production DB write, or Redis flush was performed. Real Redis saturation remains Task 7, as specified.

## Self-review

Read the implementation/new files and own diff, including all mechanical fixture/filter updates. Fixed two substantive issues identified during review: shared Celery app closures and dispatcher recovery transaction persistence. Regression tests now cover actual normal/retry task mailbox rejection, mixed queue budget fairness, broker failure retention, physical leader loss, lock retention across nested session commits, and persisted recovery. Removed the obsolete worker dispatch helper so existing dispatcher tests exercise the production standalone path. PG send drain and receipt replay tests passed along with the existing full five-second pacing tests.

## Files

- New: `src/fmg_agent/dispatch.py`, `src/fmg_agent/mail_runtime.py`, `migrations/versions/0013_mail_runtime.py`, `tests/test_queue_isolation.py`, `tests/test_mail_runtime.py` (all under `agent-service`).
- Implementation: `worker.py`, `outreach.py`, `email/retries.py`, `email/sending.py`, `email/monitor.py`; `deploy/agent-services/compose.yaml`.
- Existing tests: `test_email_worker.py` now calls standalone dispatcher; sending, PG pacing, local CLI and migration fixtures explicitly release runtime gates. Pending queries in bounce, safety, inbox, invalid-recipient, outreach, pacing, diagnostics and template regressions now explicitly specify `ontologyplay`.

## Handoff / boundaries for Tasks 7–8

- Compose services: `worker` is now enrichment; new `mail-worker`, `mail-worker-second` (profile `second-mailbox`), `dispatch`, `monitor`. Primary mailbox comes from `${FMG_AGENT_PRIMARY_MAILBOX:-ontologyplay}`; second comes from `${FMG_AGENT_SECOND_MAILBOX:-unconfigured}` and does not start by default. Explicitly starting an unconfigured mailbox fails registry selection; credentials are never inherited from the first profile.
- All roles share private `env_file` and the named `microsoft-oauth:/srv/microsoft-oauth` mount. API additionally retains `twitch-oauth`. The owner-only registry file and each profile token path must be visible consistently inside every role; Task 8 must supply/review the deployment file placement/mounts.
- Per parent direction, `deploy.sh` stop/up changes and safe hold/backfill/release procedure remain Task 8. Existing script still names only api/worker, so this intermediate task commit is NOT independently deployable. Task 8 must include all roles and optionally the second profile.
- Admin release can call `check_readiness(...)` then `set_runtime(..., dispatch_enabled=True, send_enabled=True)`. `set_runtime` itself is a low-level administrative function, not a public API and not a replacement for deployment readiness/backfill verification. Hold uses both false and waits for shared locks to drain.
- API startup/read-only access remains available in maintenance; send paths fail closed. Per parent clarification, additional API health/readiness display and cross-role release checks belong to Task 8; no new public route was added here.
- The old CLI/worker E2E fixture and opt-in container release test still assume the old embedded dispatcher/queue entrypoint; Task 7/8 must migrate those integration harnesses alongside real Redis and container validation. Their skips are not treated as deployment validation.
- SQLite is only an offline functional-test substrate. Cross-process lock guarantees are PostgreSQL-only and were tested on the supplied isolated native PG database.
- PostgreSQL guards cannot atomically roll back an external Redis/mail side effect on connection loss. Every publish is checked; durable pending state and send idempotency make duplicate publication safe. An uncertain transport remains protected by existing unknown/no-auto-retry handling.
