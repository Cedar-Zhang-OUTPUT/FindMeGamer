# Shared collection switches implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline with TDD and one
> bounded independent integrated review. Do not change frontend or running stacks.

**Goal:** Cloud-shared per-platform collection switches stop subsequent acquisition
without deleting saved data, falsely reporting exhausted sources, or starting paid replay.

**Architecture:** Add a JSON settings map to the existing singleton, a typed Settings
read/update API, and a small shared policy repository. Check policy at Discovery page
reservation, Analyze creation/handle resolution and worker claim, and scheduled selection.
Keep per-query provider conditions and saved cursors. Turning a switch on only saves
configuration; explicit query continuation/resumption controls existing paused work.

**Tech Stack:** Existing FastAPI/Pydantic/SQLAlchemy/PostgreSQL/Alembic/Celery.

**Spec:** Root coordinator's explicit shared-collection-switch instruction, PRD751
P15 Settings placeholder, docs/prd-acceptance-matrix-2026-09-08.md. This unit is the
switches only, not all remaining PRD functions listed in that matrix.

## Global constraints

- Internal stable Demo, one maintenance migration0013→0014; no rolling requirements.
- YouTube/X default enabled; Twitch/Instagram default off and unimplemented presets.
- Enabled, implemented, credential configured, and live availability are different.
- No real provider calls, SMTP, Keychain, production configuration, frontend or deploy.
- In-flight bounded acquisition may finish and save; check before next page/new task.
- Existing Library, works, matches, selections, contacts and email history survive.
- Re-enable does not automatically dispatch or replay a paused paid request.
- TDD and one fixed-scope review; only ordinary workflow/data/security/migration issues block.

## Task1: shared policy and typed Settings

Files: models/settings.py; new repositories/collection_settings.py; schemas/settings.py;
api/routes/settings.py; migrations/versions/20260908_0014_collection_settings.py;
tests/integration/test_collection_settings.py.

Interface: GET `/api/v1/settings/collection` returns items in platform order,
each with platform/enabled/implemented/credentials_configured/availability. PUT
`/api/v1/settings/collection/{platform}` accepts `{enabled: boolean}` and returns
the same collection projection. Unknown platform404, nonboolean422, auth required.
Availability is disabled/not_implemented/missing_connection/configured_unverified;
no successful live provider access is inferred from possessing a key.

- [ ] Write and run failing HTTP read/default/update/persistence/auth tests:
  `assert auth_client.get('/api/v1/settings/collection').status_code == 200`.
- [ ] Add singleton JSON column with empty-object default, policy fallbacks above,
  typed schemas and locked single-platform update preserving other settings/secrets.
- [ ] Run the focused tests; verify toggling Instagram on stays not_implemented.

## Task2: Discovery boundaries and explicit recovery

Files: workers/discovery_tasks.py; repositories/discovery.py;
tests/integration/test_collection_discovery.py.

Interface: policy `collection_enabled(session, platform) -> bool`. Disabled provider
state keeps its prior cursor/coverage/source status, adds blocked_reason=collection_disabled.
Never replace exhausted/failed with a fake status. Worker skips only that provider;
if all usable providers are disabled it pauses query with reason collection_disabled.
No sources implemented gives recoverable no_available_sources, not completed zero-results.
Explicit continue uses the same preserved cursor after enable. Settings PUT has no dispatch.

- [ ] Red test: a fixture first page disables YouTube mid-call, returns a cursor;
  assert result_count==1, one page only, cursor preserved, query paused not exhausted.
- [ ] Green policy at page reservation; retain original provider outcome separately
  from the administrative block and use explicit recoverable batch reason.
- [ ] Red/green mixed YouTube-disabled/X-enabled and all-unimplemented tests; neither
  other-platform results nor previous candidates are removed. Explicit continue after
  re-enable consumes the saved cursor, never restarts the previous paid page.

## Task3: Analyze and scheduled acquisition boundaries

Files: api/routes/jobs.py; repositories/jobs.py; repositories/profiles.py;
workers/analysis_tasks.py; schemas/jobs.py; tests/integration/test_collection_analysis.py.

Interface: disabled YouTube rejects a new acquisition with409 collection_disabled
before external handle resolution and before new job insertion. Existing jobs/profiles
remain readable. Scheduled due selection excludes disabled YouTube before limit so
Games are not starved. The old four-state Analysis contract is retained if practical:
queued work exposes an explicit waiting_reason and requires an explicit resume after
enable; do not hide paused work forever as plain queued or manufacture failure.

- [ ] Red test disabled Creator submission: assert409 and no resolver/dispatcher/job;
  Game submission remains accepted. Cover explicit retry and seed insertion boundary.
- [ ] Red test prequeued Creator worker delivery after disable: no pipeline/network,
  existing Profile unchanged; read exposes recoverable collection-disabled reason.
- [ ] Implement minimal pause projection/resume contract without general task redesign.
- [ ] Red/green scheduler disabled Creator + due Game yields only Game; no next-date
  rewrite or switch-on-triggered dispatch. Running bounded work is not invalidated.

## Task4: integrated verification and handoff

- [ ] Migration test0013→0014 preserves secrets, intervals and saved data; one linearhead.
- [ ] Update OpenAPI manifest and generated contract; document backend/API boundaries.
- [ ] Run focused then full suite in fmg-v2-tests only:
  `docker compose -p fmg-v2-tests -f backend/compose.test.yaml run --rm --no-deps
  -e REAL_REDIS_URL=redis://redis-test:6379/0 test pytest -q --tb=short`.
- [ ] One read-only integrated independent review, fix substantiated blockers only.
- [ ] Explicit-stage local safe-point commit; notify root/frontend, no push/deploy.

Self-check: credential state never implies access; policy blocks acquisition rather
than historical reads, matching or email. Per-query selection is still independent.

## Execution ledger

Tasks1–3 implemented under TDD: initial missing routes, blocked-provider continuation,
queued/running pause and source-checkpoint preservation each reproduced before code.
The chosen minimal Analysis projection retains its original four statuses and adds
collection_paused/waiting_reason/resume_available plus explicit idempotent resume.
Successful resume replay does not redispatch; queue failure restores a recoverable
pause. Coordinator confirmed bounded provider-page/fetch_creator units rather than
interrupting individual HTTP calls; new visual/contact wave also checks policy.
Focused new settings/discovery/analysis and pipeline tests passed. One independent
integrated read-only review returned ready/no blocker. Initial full suite exposed
old zero-DB-before-handle assumptions; updated to one short read-only policy query.
Three obsolete live-old-worker migration scenarios are explicitly deferred under
the user's maintenance-window boundary; current0013→0014 migration is still tested.
Final full regression passed2140 tests with3 documented deferred skips and one
existing Starlette warning in162.29s. Current0013→0014 preservation passed;18 tests
were added. Single review ready/no blocker. Root-owned PRD/matrix/outreach handoff
files stay outside this unit's index. All four tasks are complete for local commit;
frontend integration and actual deployment remain outside this increment.
