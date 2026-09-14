# Native Discover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add explicit native Discover → selected Analyze → optional Library-wide Match, with YouTube and X and curated cross-platform Profile support.

**Architecture:** Keep the released native service lineage. Introduce generic creator identity, an X analysis adapter, a small persistent discovery service, and a durable selected-analysis batch coordinator. Native SwiftUI consumes real generated API contracts and keeps selection local.

**Tech Stack:** SwiftUI/Swift 6.1, macOS 14+, Python 3.13, FastAPI/Pydantic, SQLAlchemy/PostgreSQL, Celery/Redis, existing DeepSeek/Gemini and artifact storage.

**Spec:** `docs/superpowers/specs/2026-09-14-native-discover-design.md` (approved for development 2026-09-14, including the live-tested removal of country filtering).

## Global Constraints

- Native SwiftUI macOS 14+; do not restore Electron or the v2 activity subsystem.
- Sidebar: Discover, Match, Outreach, Library, Settings. UI and generated analysis stay English.
- Discover searches homepages only; explicit Add Analysis submits the selected subset.
- Automatic Match uses all eligible Library creators, not only the Discover selection.
- Twitch/Instagram live collection is unavailable. YouTube/X are real adapters, with honest credential/quota errors.
- No country filter. Optional content-language and follower filters require observed metadata; unknown is not a verified match.
- At most 100 unique discoveries per run, bounded external requests, no promise to fill the limit.
- No credentials in frontend, fixtures, logs or commits. No real emails, data reset, production migration, deployment or publishing during development.
- Preserve successful Profiles, manual overrides, contacts and historical snapshots. Selection toggles are local, not cloud writes.
- TDD and independent review. Only normal-flow failures, data loss/duplication, credential/SSRF/duplicate-send risks, current-version migration failures and actual colleague-facing errors block acceptance. Defensive minors are recorded without scope growth.
- All model configuration continues to use `deepseek-flash`. Reuse existing email fallback and multiple contacts; do not invent watched-content evidence.
- Work only in `/Users/cedar/Documents/ChatGPT/FindMeGamer/.worktrees/native-profile-editing`, branch `codex/native-profile-editing`.

## Execution and contract boundaries

Run implementers sequentially because platform identity touches shared repository/runtime files. Review a completed unit while the controller prepares the next handoff, not by running another implementation against the same files. Models use `gpt-6-astra`, `medium` as requested by the user.

Backend test command (from `backend/`):
```sh
docker compose -p fmg-native-edit -f compose.test.yaml run --rm test pytest -q
```
Native command (worktree root):
```sh
swift test --package-path macos --no-parallel
```
Use focused test paths during iteration. Full suite once per completed unit; existing three postponed backend tests and recorded warning remain explicit. Do not use live/cloud DB in tests.

## Task 1: Platform-neutral identity and native migration

**Files:**
- Create `backend/app/analysis/creator_identity.py`.
- Create `backend/migrations/versions/20260914_native_0009_creator_identity.py`.
- Modify `backend/app/db/models/profiles.py`, `backend/app/repositories/profiles.py`, `backend/app/repositories/jobs.py`, `backend/app/analysis/service.py`, `backend/app/api/routes/profiles.py`, `backend/app/schemas/profiles.py`.
- Inspect downstream identity checks in `backend/app/services/profile_editing.py`, `backend/app/repositories/match.py`, `backend/app/analysis/creator_checkpoints.py`; modify only needed identity assumptions.
- Test `backend/tests/unit/analysis/test_creator_identity.py`, `backend/tests/integration/test_creator_identity_migration.py`, `backend/tests/integration/test_creator_platform_profiles.py`.

**Interfaces:** `CreatorProfile.platform: str` (`youtube`, `x`, `twitch`, `instagram`), `platform_account_id: str`, nullable legacy `youtube_channel_id`. Unique `(platform, platform_account_id)`. `creator_job_identity(platform: str, account_id: str) -> str` preserves bare YouTube IDs; other IDs use `<platform>:<id>`. `CreatorProfileCard/Detail` expose new identity fields and nullable legacy ID. Existing YouTube JSON remains readable; native decoding adaptation occurs in Task 5.

- [ ] Write red tests for `creator_job_identity('youtube', 'UCexample123') == 'UCexample123'`, `creator_job_identity('x', '12345') == 'x:12345'`, rejecting unsupported platform/blank identity; two platforms with same account ID remain distinct.
```python
def test_creator_job_keys_do_not_collide():
    from app.analysis.creator_identity import creator_job_identity
    assert creator_job_identity('youtube', 'UCexample123') == 'UCexample123'
    assert creator_job_identity('x', '12345') == 'x:12345'
    assert creator_job_identity('twitch', '12345') == 'twitch:12345'
```
- [ ] Add migration fixture at native `0008` with a YouTube Profile, contact, manual overrides and completed job; upgrade and assert unchanged IDs/facts/contact/overrides plus backfilled platform identity. Test new X row persists/reads/edits without a fake YouTube ID. Use the real API fixture and existing Profile constructors.
- [ ] Run focused tests and record expected RED before implementation.
- [ ] Implement additive migration/backfill and model identity handling. Existing YouTube constructors/writes must still populate new identity correctly; do not break every established fixture or producer. Use a focused ORM insert normalizer if needed, not per-request migration. Public display and editing remain same effective-data behavior. Existing jobs retain their canonical IDs. Unsupported-platform due reanalysis must not enqueue doomed jobs.
```python
def creator_job_identity(platform: str, account_id: str) -> str:
    if platform not in {'youtube', 'x', 'twitch', 'instagram'} or not account_id or account_id.strip() != account_id:
        raise ValueError('Invalid creator identity')
    return account_id if platform == 'youtube' else f'{platform}:{account_id}'
```
- [ ] Run focused identity/migration/profile-edit/job regressions, then full backend; report actual output and commit only task files. Export OpenAPI only if needed for current contract tests; do not hand-edit generated Swift types.

## Task 2: X URL resolution and full Creator analysis

**Files:** Create `backend/app/integrations/x.py`, `backend/app/analysis/x_creator_pipeline.py`, `backend/app/analysis/prompts/x_creator.py`, `backend/migrations/versions/20260914_native_0010_x_analysis.py`; modify `analysis/targets.py`, `analysis/runtime.py`, `analysis/service.py`, `analysis/contracts.py`, `core/config.py`, `core/analysis_job_contract.py`, `integrations/connection_probe.py`, `schemas/settings.py`, `api/routes/settings.py` only for X support. Tests in `tests/unit/integrations/test_x.py`, `tests/unit/analysis/test_x_creator_pipeline.py`, `tests/integration/test_x_creator_analysis.py` and existing target/runtime/worker tests.

**Interfaces:** X homepage aliases resolve through official user lookup to stable account ID and canonical `https://x.com/i/user/{id}`; internal canonical target key is `x:{id}`. Extend the existing resolver/runtime instead of bypassing JobsRepository. `XGateway` supports account lookup and recent public content; `XCreatorAnalysisPipeline` produces the existing common Creator analysis/Brief contract with platform-specific facts and source references. No fabricated video statistics or YouTube identity.

- [ ] Write red target tests for x.com/twitter.com username aliases, stable-ID URL, status URL rejection and cross-host/credential URL rejection. Unit HTTP fixtures must assert request host/path/authorization handling, not expose a real token.
```python
def test_x_id_url_is_namespaced():
    from app.analysis.targets import canonicalize_target
    from app.db.models.enums import TargetType
    target = canonicalize_target(TargetType.CREATOR, 'https://x.com/i/user/12345')
    assert target.canonical_id == 'x:12345'
```
- [ ] Add real-persistence analysis tests: account/posts → common Profile/Brief; missing public email invokes existing Gemini fallback; multiple contacts retain purpose; failed refresh retains prior Profile/manual overrides. Missing X configuration/402/403 spend cap/429 become distinct safe errors, not empty success. No-video/visual-unavailable is explicit, not fatal invented media.
- [ ] Additive native0010 migration must replace the succeeded-job validation SQL function introduced in `20260902_0004_analysis_job_public_state.py` to accept true generic identity and safe canonical X URLs without weakening YouTube validation. Test actual X successful publication against the migrated DB, not merely ORM Profile insertion. Coordinate native Match freshness checks currently keyed to YouTube source status so real X source evidence is eligible without masquerading as YouTube.
- [ ] Extend public Creator identity DTOs and serializers in `schemas/match.py`, `schemas/outreach.py`, their route/repository consumers, and required source editability rules. These still require `youtube_channel_id` in the baseline. Test reading X through Match and outreach preview, not just Library; no fake legacy ID and no real send.
- [ ] Run focused RED, implement X gateway and pipeline using existing HTTP safeguards, artifact provenance, optional email fallback and DeepSeek configuration. Reuse existing validation instead of restoring v2 activity logic. Keep checkpoint/retry behavior consistent for completed stages.
- [ ] Run focused GREEN + existing YouTube worker/contact/Match regressions + full backend. Commit and report exact supported X account/content endpoints for later real acceptance.

## Task 3: Durable Discover search and game prerequisite

**Files:** Create `backend/app/schemas/discover.py`, `db/models/discover.py`, `repositories/discover.py`, `api/routes/discover.py`, `discovery/service.py`, `discovery/runtime.py`, `discovery/planning.py`, `integrations/youtube_discovery.py`, `integrations/x_discovery.py`, `workers/discover_tasks.py`, migration `20260914_native_0011_discover.py`. Register in `db/models/__init__.py`, `main.py`, existing Celery application/Beat configuration. Tests `tests/unit/discovery/test_discover_providers.py`, `test_discover_planning.py`, `tests/integration/test_native_discover.py` and migration test.

**Interfaces (freeze DTOs here before native work):**
- `POST /discover/resolve-game`: `{steam_url}` → `{steam_app_id, name, canonical_url, game_id?}`; public Steam metadata lookup only, no analysis job.
- `GET /discover/capabilities`: platform availability and safe reason, no secrets.
- `POST /discover` with `Idempotency-Key`: `{game_id? OR steam_url?, conditions:{platforms, content_languages:[], min_followers?, max_followers?, keywords:''}}` → Discover detail.
- `GET /discover?cursor=...` → `{items,next_cursor}` with compact summary rows (identity/game/status/stage/counts/timestamps; no candidate bodies); `GET /discover/{id}` → `{id,game_id?,game_name,status,stage,conditions,candidates,issues,created_at,updated_at}`.
- `POST /discover/{id}/retry` idempotent, only incomplete work.
- Candidates: `{id,platform,platform_account_id,display_name,canonical_url,followers?,content_languages:[],in_library,profile_id?}`.
- Internal status `queued|running|done|partial|failed`; stage `preparing_game|finding_creators|null`. UI may display corresponding readable labels.

- [ ] Red API tests create one persistent job, reject no game/both game inputs/unavailable platforms/inverted follower bounds; same idempotency request returns same job, changed payload conflicts. No Creator Profile is inserted merely by discovering it.
```python
# In authenticated API integration fixture:
response = client.post('/discover', headers={'Idempotency-Key': request_key}, json=payload)
assert response.status_code == 202
assert response.json()['status'] == 'queued'
```
- [ ] Test missing Steam game joins/creates Game Analysis and resumes after success; failed game blocks search. Existing game/manual overrides reused. Recovery survives coordinator restart. Use API + DB + worker entry point with stub external providers, not fake completed business methods.
- [ ] Provider RED cases: videos→author dedup, X posts→author dedup, <=100 across platforms, bounded next-page handling, subscriber postfilter, language metadata missing, 402/403/429, one platform failure preserving the other. Search plan uses effective Game context and keywords, never a mandatory exact intersection of every reference game. Old v2 adapters can be selectively ported after tests; their persistence/workflow must not be copied.
- [ ] Implement short transactions around persistent stage transitions; external IO outside DB locks. Claim/lease or existing worker pattern prevents duplicate publishes. Beat sweeps resumable queued/prerequisite jobs with bounded work. No extra hosted service. Export real OpenAPI with project generator and regenerate copied native schema.
- [ ] GREEN provider/API/worker/migration tests then full backend. Commit an API contract ready for Task 4/5.

## Task 4: Selected Analyze batch and exactly-once automatic Match

**Files:** Create `backend/app/schemas/discover_batch.py`, `db/models/discover_batch.py`, `repositories/discover_batch.py`, `discovery/batches.py`, `workers/discover_batch_tasks.py`, migration `20260914_native_0012_discover_batches.py`. Extend Discover routes/runtime, worker registration and exported OpenAPI. Tests `tests/integration/test_discover_analysis_batches.py`, `test_discover_auto_match.py`.

**Interfaces:** `POST /discover/{id}/analysis-batches` with idempotency key and `{candidate_ids:[UUID],mode:'analyze'|'analyze_and_match'}`; `GET /discover/{id}/analysis-batches` → history; `GET /discover/{id}/analysis-batches/{batch_id}` → `{id,discover_id,mode,status,items:[{candidate_id,profile_id?,analysis_job_id?,status,reused,error?}],match_task_id?,error?}`. `reused` explicitly distinguishes usable-Profile reuse from newly analyzed success. Cancel has no endpoint because it makes no submission. Use existing `JobsRepository` and `MatchRepository.create_locked_task` transaction semantics. Unique persisted batch follow-up Match link.

- [ ] Red API/DB tests prove only selected IDs processed, reject IDs belonging to another Discover, stable idempotency replay, reuse usable Profiles, join running analysis, no email dispatch.
- [ ] Red worker test starts with an old eligible Library creator plus selected newly analyzed creator; terminal mixed-success batch creates one ordinary Match with both eligible creators. Duplicate delivery creates no extra Match. Replaying failed analysis after Match creation doesn't automatically create another Match.
```python
# Use real Match repository and persisted analysis outcomes in worker integration test.
assert persisted_batch.match_task_id is not None
assert set(locked_creator_ids) == {old_creator.id, newly_analyzed_creator.id}
```
- [ ] Implement durable batch item/job associations and bounded resume sweep; reuse existing validation/freshness rules, not `last_analyzed_at != null` alone. Preserve successes on partial errors. Empty eligible Library/game invalid surfaces blocked state. Dispatch after commit; failed dispatch remains recoverable without duplicate jobs.
- [ ] GREEN new integration tests + existing Match/analysis idempotency/checkpoint tests + full backend; export API and commit.

## Task 5: Native Discover experience and X-compatible Profiles

**Files:** Create `macos/Sources/FindMeGamerCore/Models/DiscoverModels.swift`, `Features/DiscoverModel.swift`, `Services/DiscoverAPIService.swift`, `macos/Sources/FindMeGamer/Views/Discover/DiscoverView.swift`, `DiscoverGamePicker.swift`, `DiscoverConditionsSheet.swift`, `DiscoverResultView.swift`. Modify Core `AppDestination`, `WorkspaceNavigationState`, `ClientCoordinator`, `AppSession`, `APIService`, `OpenAPIService`, `DomainMapper`, `DemoAPIService`, Profile/Settings models and UI representations. Modify `SidebarView`, `AuthenticatedRootView`, `AnalyzeRequestInspector` and platform display where required. Tests `macos/Tests/FindMeGamerCoreTests/DiscoverModelTests.swift`, `DiscoverServiceTests.swift`, `CreatorPlatformTests.swift`, UI presentation tests under existing UI test target.

**Interfaces:** `DiscoverModel` loads capabilities/history, resolves selected game, submits conditions, polls active record, holds `Set<UUID>` selected IDs locally, and submits the explicit analysis mode through Task 3/4 endpoints. `APIService` gains typed Discover methods and Demo implementation; real mode never silently falls back to Demo. Generated OpenAPI DTOs match backend snapshot. Extend profile identity mapping to nullable legacy ID and real platform account ID; don't label X metrics as YouTube video metrics.

- [ ] RED tests: correct sidebar ordering/default; >3 games still reachable/searchable, select all/deselect all includes offscreen records with no API write, Cancel doesn't submit, mode choice emits one batch with retained key on uncertain response. Partial errors retain prior rows/input and do not lock user out of Settings.
```swift
// Against the actual DiscoverModel with a recording API test double:
model.selectAll()
#expect(model.selectedIDs == Set(candidates.map(\.id)))
model.deselectAll()
#expect(model.selectedIDs.isEmpty)
#expect(service.submittedBatches.isEmpty)
```
- [ ] Implement game pill/popover with three-row viewport and scrollable paginated results, URL resolution feedback; Start → one modal with available platforms, language, followers, keywords; history table and selected-results Add Analysis flow. Use native sheet/popover/table patterns and existing standard-control fallbacks. One main task focus, no old activity dashboard or auto-evaluation buttons.
- [ ] Poll visible/in-flight work with cancellation on session/workspace switch; preserve local drafts/selections. Disclose failures without hiding successful rows. Link ordinary Match after automatic creation. Add X Settings credential/status support and allow public X URL analysis.
- [ ] GREEN focused tests, complete Swift tests and app build; actual UI walkthrough scrolling/keyboard/selection/Cancellation. Commit without packaging/publishing yet.

## Task 6: Curated Twitch/Instagram import contract

**Files:** Create `docs/creator-import/README.md`, `creator-import.schema.json`, `twitch.example.json`, `instagram.example.json`; create `backend/app/schemas/creator_import.py`, `backend/app/cli/import_creator_profiles.py`, tests `tests/unit/test_creator_import_contract.py`, `tests/integration/test_creator_import.py`. Adapt `backend/app/repositories/match.py` and source visibility consumers only as required for honest curated-source eligibility.

**Interfaces:** `python -m app.cli.import_creator_profiles --file INPUT --dry-run` validates a versioned `schema_version:1` envelope with records carrying platform identity, canonical URL, public facts, dated works/evidence/metrics, contacts with purpose/source, optional validated common analysis/Brief. Explicit non-dry-run import is idempotent by platform/account identity and refuses overwriting an existing manually edited Profile without explicit conflict handling. No actual data import as part of development.

The early handoff in `docs/creator-import/COLLECTION-HANDOFF.md` and `*.collection-template.json` is already shared with colleagues. Also accept/normalize its `collection_schema_version:1` envelope without losing fields. Unknown account IDs may be collected but must be resolved/confirmed before Library insertion; dry-run reports those records as needing identity resolution. Do not require colleagues to rewrite supplied work evidence into internal AI response schemas.

- [ ] Research official Twitch and Meta APIs, record field availability and whose authorization is required; distinguish obtainable from optional/private/unavailable. Shared Profile core with typed native metrics, not coerced YouTube fields. Country/language/email may be unknown.
- [ ] RED contract tests accept supplied fact-only fixtures but do not make them Match-eligible until valid analysis/Brief exists; reject identity/source mismatches, secret-bearing fields and duplicate contact noise. Roundtrip template/schema uses real Pydantic validation, not source-text assertions.
- [ ] Prove a source-bound curated record with valid common analysis/Brief and current analysis timestamp can enter an ordinary Library-wide Match. Task2 freshness currently allows only YouTube/X: extend eligibility for explicitly curated Twitch/Instagram provenance without pretending their live source is available. Fact-only records remain ineligible; automatic acquisition remains disabled. Retain existing freshness cutoff rather than granting permanent eligibility.
- [ ] Implement validation/dry-run and explicit import transaction, preserving manual ownership and disabling unsupported automated reanalysis. Deliver empty fillable templates separately from clearly synthetic test examples. No fake public person claims in fixtures.
- [ ] GREEN test schema examples and DB dedup/manual protection, commit research and contract. Provide the user required fields, not only technical research prose.

## Task 7: Whole-flow acceptance and release handoff

**Files:** Create `backend/tests/native_discover_http_fixture.py`, `macos/Tests/FindMeGamerCoreTests/NativeDiscoverHTTPAcceptanceTests.swift`, `docs/native-discover-acceptance-2026-09-14.md`; amend uncovered behavior in owning files only with regression tests.

- [ ] Red/green integration acceptance uses isolated DB/API/Worker and native real HTTP client: new Steam game prerequisite → discover → local subset selection → Analyze → automatic all-Library Match. Include reused Creator, partial failure, duplicate request/restart and unavailable channel. External model/provider fixture is explicitly simulated; no claim this alone is live acceptance.
- [ ] Run bounded real YouTube/X discovery and selected one-account analysis with explicit existing user authorization for development tests; never real SMTP. Stop on credit/cap issues, retain evidence and do not raise spend limits. This acceptance cannot be substituted by API-only feasibility probe results.
- [ ] Run final backend and Swift suites, native build, migration from current native head on isolated DB, API snapshot compatibility and one whole-branch independent review within Demo blockers.
- [ ] Produce exact tested commit, test evidence, remaining limitations, deployment/backup commands and package readiness. Do not migrate production, publish GitHub assets or reset data under this development-only request. Ask for release execution after the verified build is ready.
