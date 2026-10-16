# Task 8 — release readiness and safe cutover

Status: **DONE_WITH_CONCERNS** for the authorized local scope; production/container gates remain closed.

## Scope and implementation

Base: `b2c8f0f`. Implemented local release tooling only. No production mutation,
SSH/deployment, Docker startup, push/tag/publication, actual mail or paid provider
calls. Existing controller native PostgreSQL/Redis roots were neither stopped nor
reconfigured. Tests use UUID schemas and Redis prefixes in the designated test
database/DB 14.

- Added `mail_runtime.py status|hold|release` plus `readiness`, `check-cutover`
  and `check-legacy-rollback`. Release is fail-closed on schema/backfill, gates,
  in-flight jobs/sends/send leases, live sender advisory locks, expected running
  roles, fresh role readiness, local mailbox configuration and old queue/unacked
  drain. Hold uses the existing exclusive runtime lock and waits for active
  shared holders; no timeout kill/reset. Only runtime flags change on release.
- Added `queue_cutover.py audit` and explicit `migrate --manifest FILE --confirm`.
  Audit is read-only unless asked to create a private recoverable snapshot. It
  captures exact raw messages and unacked evidence, known/unknown/type/ID counts
  and DB-state aggregates. Snapshot is checksummed and bound to DB/schema/broker.
  Unknown/unacked data blocks migration before publication. DB state selects
  queued enrichment, approved/unattempted recipient and legal due retry routing;
  no sent/unknown/prior-attempt replay. Disabled/paused/unapproved work remains in
  DB. Exact one-message acknowledgement follows publication, with a fsynced
  reconciliation journal for the non-atomic cross-queue boundary. Repeated
  migration reports already-absent items; no purge/FLUSHALL.
- Deployment saves private config/container evidence, disables automatic
  resurrection of old containers, requests SIGTERM for all running roles and
  waits for warm exit. A drain deadline aborts without SIGKILL or startup.
  Database backup, migration, hold, actual gate/in-flight checked backfill and
  audited queue migration precede force-recreation of the five primary roles.
  The second-mailbox profile remains unused. Script verifies readiness and ends
  held; it never changes proxy routes or releases gates.
- Added read-only private registry mounts for every agent role and migration,
  explicit disabled/no-credentials second-mailbox example, mailbox discovery in
  read-only smoke, deployment/rollback runbook and actual artifact verification.
- Controller explicitly approved a focused runtime scope extension:
  `fmg_agent/role_health.py` plus worker/dispatcher/monitor hooks. Artifacts bind
  role, mailbox, expected schema, DB configuration fingerprint, queue, pool size,
  PID/start identity and timestamp, inside each container's own filesystem.
  Worker readiness is written only after consumer startup and from a heartbeat
  checking broker connection, actual configured consumer queues and 4/2 pool
  size. Dispatcher readiness follows a successful iteration. Monitor readiness
  follows a held local check or non-error scan and is cleared on errors/exit.
  Probe checks freshness (30s, or 2*monitor poll+10s) and live PID/start identity.
  This is local readiness, explicitly not remote provider connectivity.
- Closed two silent-start gaps: global hold now prevents monitor upstream scans
  and enrichment consumers' provider construction/execution. SenderSafety alone
  still permits monitoring. Enrichment holds a shared runtime lock while working,
  so global hold also drains paid work without changing task budgets/retries.
- Strengthened Task 7's crash duplicate assertion: a fresh marker task proves
  replacement pool progress, then bounded polling proves broker queues and
  unacked ledger drained before asserting the original accepted send was not
  repeated. Removed the unsupported fixed 11-second assumption.

## TDD evidence

Commands below run from `agent-service`, with:

```sh
FMG_AGENT_TEST_DATABASE_URL=postgresql+psycopg://fmg_agent_test@127.0.0.1:55441/find_me_gamer_agent_test
FMG_AGENT_TEST_REDIS_URL=redis://127.0.0.1:55442/14
FMG_AGENT_TEST_CLI=../cli/fmg
```

RED observations before corresponding implementation:

1. `.venv/bin/pytest tests/test_deploy_tools.py -q`: **5 failed, 4 passed**.
   Required in-flight, unmapped release, legacy rollback, read-only maintenance
   and unknown-audit tests reported missing deployment safety tools.
2. Role-evidence/monitor tests: **8 failed, 10 passed**, because `role_health`
   did not exist. After implementation, **28 passed / 1 failed** exposed native
   `ps` failure normalization for a nonexistent PID; corrected to fail cleanly.
3. Audit/restart/snapshot tests: **2 failed, 18 passed**, missing queue `main`
   and `audit` implementation. GREEN: **20 passed** with real PG/Redis.
4. Warm-drain and preflight tests: **2 failed, 20 passed**. Old deploy rejected
   the proxy-blocked workflow; old `--apply --quiescent` incorrectly succeeded
   with open runtime gates. GREEN after orchestration/gate integration:
   **22 passed**.
5. `.venv/bin/pytest tests/test_deploy_tools.py::test_held_enrichment_consumer_makes_no_paid_call -q`:
   **1 failed**, specifically `held worker constructed provider`. Added the
   shared runtime gate before factory execution; subsequent focused runs pass.
6. Legacy-queue release and local credential readiness: **2 failed, 26 passed**,
   missing `legacy_drained` and unconfigured enabled mailbox incorrectly passing
   its probe. Added checks; subsequent focused runs pass.

One early test fixture used `get_secret_value()` on the plain-string database
URL; corrected before GREEN. The existing Starlette/AnyIO deprecation warning
appears in Python runs and is not silenced.

## Verification results

- Final focused command:
  `.venv/bin/pytest tests/test_deploy_tools.py tests/test_mailbox_migration.py tests/test_mailbox_monitor.py tests/test_queue_isolation.py -q`
  — **56 passed, 1 warning in 16.47s**. Includes actual real-Kombu publication via
  the queue CLI entrypoint, exact acknowledgement, incomplete-drain refusal,
  native PG custom-format backup/restore, old-schema upgrade/backfill with frozen
  history, identity mismatch refusal, monitoring behavior and runtime isolation.
- Earlier focused real-role/crash command:
  `.venv/bin/pytest tests/test_deploy_tools.py tests/test_queue_isolation_integration.py::test_real_roles_emit_fresh_local_readiness tests/test_queue_isolation_integration.py::test_worker_loss_keeps_unknown_unreplayed -q`
  — **30 passed, 1 warning in 36.01s**. Real API/CLI, dispatcher, monitor and
  prefork workers, with only external providers replaced by virtual transports.
- Full required `.venv/bin/pytest` after code freeze: **494 passed, 1 skipped,
  1 warning in 651.14s (10:51)**, exit **0**, 495 collected. No native integration
  skip. The sole skip is
  `tests/test_release_container.py::test_local_release_image_and_restore`, because
  `FMG_AGENT_TEST_IMAGE=fmg-agent:predeploy` was intentionally not enabled under
  the no-Docker constraint. Actual terminal execution session: `73490`; final
  output chunk: `945aa8`. The command was not tee'd to a separate raw log; this
  report preserves the exact terminal result, rather than inventing a log path.
  Final resource artifact confirms **20 baseline + 20 dual virtual sends**, **20
  terminal enrichments**, `broker_drained: true`, eight worker children and 1,110
  samples. Baseline/dual p95: **190.539s / 100.260s**; elapsed **200.581s /
  100.335s**; peak RSS **837,697,536 / 1,018,494,976 bytes**; peak DB connections
  **14 / 26 of 100**. The resource gate passed with the new health/runtime hooks.
- `cd cli && ../.local/toolchains/go1.27.1/go/bin/go test ./... && ../.local/toolchains/go1.27.1/go/bin/go vet ./...`
  — exit **0**, CLI internal package passed (Go test cache), command package has
  no tests; vet clean.
- `GO="$PWD/.local/toolchains/go1.27.1/go/bin/go" sh cli/scripts/build-release.sh fmg-v0.8.0 .local/releases/fmg-v0.8.0`
  — exit **0**, four platform archives, Skills archive, installer and SHA sums.
- `FMG_RELEASE_DIR="$PWD/.local/releases/fmg-v0.8.0" FMG_RELEASE_VERSION=0.8.0 agent-service/.venv/bin/python -m pytest cli/tests/test_release_bundle.py cli/tests/test_installer.py -q`
  — **4 passed in 1.16s**, zero skips. Checks all four platform SHA sums, actual
  native CLI version, both installed Skill versions, upgrade backups and repeated
  offline install preserving authentication bytes and mode 600.
- `sh cli/tests/skill_examples.sh` initially ran both executable simulations
  successfully, then correctly refused missing native-service variables. Rerun
  with the above explicit DB/Redis variables — exit **0**, both simulations pass
  and **4 passed, 1 warning in 64.20s** for e2e/workspace integration. No actual
  provider calls.
- `git ls-remote --tags origin refs/tags/fmg-v0.8.0 'refs/tags/fmg-v0.8.0^{}'`
  — exit **0**, no matching tag at read-only check time. Not a reservation.
- `git diff --check` and `sh -n deploy/agent-services/deploy.sh deploy/agent-services/smoke.sh`
  — exit **0**.
- Browser preview/Skill behavior acceptance was already controller-verified for
  Task 6/7; this task does not modify UI or Skill production content. It was not
  redundantly rerun as a new browser session here.

## Local artifact hashes

Directory: `.local/releases/fmg-v0.8.0` (ignored local output, not committed).

| Asset | SHA-256 |
| --- | --- |
| fmg_darwin_arm64.tar.gz | f99006581aadada893dd6ef0ba51f493bf3081d3f2c4d6c1073edd597d341dbb |
| fmg_darwin_amd64.tar.gz | 5acf905f884171a6cd06a0cbb11b73ef51992b18b71b4d3521ee640e1f1989c5 |
| fmg_linux_arm64.tar.gz | 13a82abc82423cd2ff29ed899b43056035b6c45f99dd98af50724f8e1f26ce6a |
| fmg_linux_amd64.tar.gz | f0858c88643601557af0fe260045509dc20f7fb97d0fa6fd60c99e1ea216a6e7 |
| fmg-skills.tar.gz | 2c55d3a196e4d140c9a4a5e7b487e2667ee85a0e67df3365fa24f81ce9a3cd3f |
| install.py | d3e9ec1b47a8af640167a2b513154230684923daa0a2082d499e174279105e6f |

## Self-review and limitations

Read own runtime, queue migration, deployment, configuration, tests and release
diff. Preserved existing sender safety, unknown reservations, approval revisions,
historical templates/images/receipts and budgets. Runtime release has no approval
or SenderSafety mutation path. Queue migration alters broker envelopes only;
eligibility queries do not write original task state. Backfill retains its
frozen before/after digest and now checks real runtime/in-flight state.

Production safety still requires operator evidence: proxy blocking is explicitly
attested by `--proxy-writes-blocked`, not independently proven by the script.
Stopped-service verification covers the supplied Compose project; independently
inventory and stop ad-hoc/other-project producers/consumers. Host admin URLs and
registry must target the same configuration as Compose. Database/schema and Redis
target equality is now independently enforced by the round-1 live challenge
described below, not left to operator attestation. Native tests
replace only Docker execution boundaries; they do not claim actual Docker
orchestration or Linux image readiness was exercised.

Container backup/restore is **blocked by the no-Docker constraint**, not passed
by native PG restore. This is an outstanding required gate and blocks rollout.
Native Redis is **8.10.1**, not production Redis 7. Warm-drain script behavior is
tested with deterministic Docker-command fixtures, while real worker processes,
broker readiness, locks and recovery are exercised natively. Production proxy,
image/registry permissions, host admin connectivity and actual container process
identity remain to be verified during an authorized rehearsal/window.

Delivery boundaries: code/local testing completed; CLI/Skills candidate built
locally but **not published**; server **not deployed**; second mailbox **disabled,
without credentials or enrollment authorization**. No production resume action
has occurred. No workflow publication change was required.

## Files

New: `deploy/agent-services/mail_runtime.py`, `queue_cutover.py`,
`mailboxes.example.json`, `docs/agent-services/multi-mailbox-deployment.md`,
`agent-service/src/fmg_agent/role_health.py`, this report.

Modified: `deploy/agent-services/deploy.sh`, `compose.yaml`, `env.example`,
`mailbox_preflight.py`, `rollback.md`, `smoke.sh`;
`agent-service/src/fmg_agent/worker.py`, `dispatch.py`, `email/monitor.py`;
`agent-service/tests/test_deploy_tools.py`, `test_queue_isolation_integration.py`;
`cli/tests/test_release_bundle.py`; native acceptance addendum (after final run).

## Review fix round 1 (base `5c09ba4`)

Addressed both Important findings. Applied test-driven-development and
verification-before-completion; evaluated review feedback against the actual
lock/probe paths (receiving-code-review).

1. Monitor now owns a shared runtime lock on a separate connection across the
   enabled check and entire scan. The monitor's fenced scan sessions may commit
   without releasing this drain lock. Both global flags must be open. Hold waits
   for the active scan; later iterations remain local-only. SenderSafety is not
   consulted by this gate, preserving monitoring during mailbox safety pauses.
2. Readiness/release creates a fresh random transaction-owned PostgreSQL advisory
   challenge and random Redis key/value (300-second TTL). Each service's probe
   must observe the administrator's lock owner/key in `pg_locks`, filtered to its
   own actual `current_database()` OID, plus the exact current schema, and read the
   Redis nonce through its own broker connection. This accepts different host
   spellings for the same targets, not merely matching configuration labels.
   Every service is covered, including an API target probe alongside HTTP health.
   Role artifacts additionally bind the broker URL hash to the live process's
   configuration; raw URLs/credentials are never emitted in probe output.
   Administrator validates returned role/mailbox/schema/queue/concurrency/nonce.
   Redis cleanup uses atomic compare-delete of only the owned key in `finally`;
   missing/expired/replaced proof or cleanup failure prevents gate opening and
   rolls back the release transaction. PostgreSQL proof expires with that
   transaction. No schema, new infrastructure, external provider call, or safety/
   approval mutation was added.

### Exact verification

All pytest commands ran from `agent-service`, with the previously listed isolated
`FMG_AGENT_TEST_DATABASE_URL` and `FMG_AGENT_TEST_REDIS_URL` environment variables.
No raw log file was created; terminal tool results are the evidence.

- RED: `.venv/bin/pytest tests/test_mailbox_monitor.py::test_hold_drains_active_monitor_scan_and_blocks_next tests/test_deploy_tools.py::test_role_target_challenge_proves_shared_services tests/test_deploy_tools.py::test_role_artifact_rejects_changed_broker -q`
  — **7 failed, 1 warning in 3.24s** (terminal chunk `dfab70`). Hold returned during
  blocked scan; challenge API absent in five variants; changed broker was accepted.
- GREEN after implementation: `.venv/bin/pytest tests/test_deploy_tools.py tests/test_mailbox_monitor.py -q`
  — **48 passed, 1 warning in 14.93s**.
- Added release-level regression:
  `.venv/bin/pytest tests/test_deploy_tools.py::test_release_validates_actual_targets_before_opening_gates -q`
  — **7 passed, 1 warning in 3.78s**. Same-target aliases release successfully;
  wrong database/schema/Redis DB, forged nonce/role and cleanup failure retain both
  closed gates, preserve protected data digest, and leave no owned challenge key.
- Final code-frozen focused run, also exercising the actual API probe CLI against
  live native PG/Redis targets:
  `.venv/bin/pytest tests/test_deploy_tools.py tests/test_mailbox_monitor.py tests/test_mail_runtime.py -q`
  — **65 passed, 1 warning in 21.60s**, zero skips (session `89942`, final chunk
  `087c87`). Includes held monitor/no-upstream, stopped-monitor refusal,
  SenderSafety-paused/still-monitors, coordinated active scan/hold, existing send
  drain, alias success and target/cleanup refusal. Warning is the existing
  Starlette/AnyIO deprecation.
- `.venv/bin/black --check src/fmg_agent/mail_runtime.py src/fmg_agent/email/monitor.py src/fmg_agent/role_health.py tests/test_mailbox_monitor.py tests/test_deploy_tools.py ../deploy/agent-services/mail_runtime.py`
  — exit **0**, six files unchanged. `git diff --check` — exit **0**.

Changed files: runtime gate, monitor, role-health module; deployment runtime tool;
deploy-tools and mailbox-monitor tests; deployment guide; this report. Self-review
checked connection ownership, current-database lock scoping, nonce lifetime and
cleanup ordering before gate writes, role-result validation, and absence of
safety/approval reset paths. Full 11-minute suite was not rerun for this scoped
fix, per controller instruction; initial full-suite evidence remains above, not
represented as a run of this patch. No container/production/release-publication
gate has been passed or newly exercised. No Docker or external-provider actions.
