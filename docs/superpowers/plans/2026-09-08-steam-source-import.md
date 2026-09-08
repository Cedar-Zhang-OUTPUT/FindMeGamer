# Steam source import Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD and one
> bounded integrated independent review. Start after C's safe local commit.

**Goal:** P1.2 explicit Steam Submit returns editable v2 GameDetail and preserves
the same Game UUID through manual editing and subsequent full Analyze.

**Architecture:** Dedicated synchronous source-only endpoint reuses canonical Steam
target validation and SteamGateway. No model/job/SMTP is created during import.
Fetch outside the shared write lock, then recheck identity/revision and atomically
publish source fields with existing idempotent-write conventions. Source import
preserves manual overrides, references and any completed analysis.

**Tech Stack:** Existing FastAPI/Pydantic/SQLAlchemy/PostgreSQL/httpx SteamGateway;
no new service, migration, secret or worker.

**Spec:** `docs/analyze-v2-implementation-handoff.md` §1, §3 Game rows, §5 Game/Steam.
YouTube URL binding, content-language projection and X Analyze are separate units.

## Global constraints

- Internal stable Demo; current maintenance-window schema, no rolling/HA expansion.
- English source fetch; genres are genres, not fabricated Steam user tags.
- Explicit POST only; typing/pasting behavior belongs to frontend, not background API.
- No source failure clears old data; existing analysis dates/results are not refreshed
  by source import. New source seed has manual_revision1 and no last_analyzed_at.
- Supplied game_id requires expected_revision and is explicit first-source binding.
  A different already-bound Steam identity returns409, never silently rebinds.
- Fixed Steam gateway base URL; input URL is canonicalized into app ID, not fetched.
- No real provider/model/SMTP, push, deployment or new credentials during verification.

## Task 1: import API and source publication

Create `backend/app/api/routes/steam_import.py`,
`backend/app/repositories/steam_import.py`,
`backend/app/schemas/steam_import.py`,
`backend/tests/integration/test_steam_import.py`; register injectable gateway factory
in `backend/app/main.py`. Reuse existing GameDetail and SteamGameSource.

```text
POST /api/v2/library/games/steam-import
Idempotency-Key
{url, game_id?:UUID, expected_revision?:int} -> GameDetail (200)
```

- [ ] Red: real SteamGateway/httpx fixture returns source name/developer/description/
  genres/languages/cover; response has same v2 types, source fields not artificial
  manual overrides, last_analyzed_at null, zero jobs/model calls. Known missing optional
  fields remain empty and source retry preserves count1 for sameSteam ID.

```python
assert result['source_fields']['name'] == 'Fixture Game'
assert result['manual_overrides'] == {}
assert result['last_analyzed_at'] is None
assert replay['id'] == result['id']
assert game_count == 1 and analysis_job_count == 0
```

- [ ] Green: strict URL/key/input pair validation, successful request replay before
  network, source lookup by canonical app ID, source-only data mapping excludingraw,
  canonical URL and effective sort name. Existing source row reused; existing claimed
  manual Steam identity without explicit Game ID conflicts instead of creating another.
  Preserve favorite/manual/reference/analysis/brief/model/prompt/analysis dates.
  Selected unbound Game adopts source ID under revision check; conflicting/changed
  identity rechecked atomically after fetch. Import increments revision once.
- [ ] Red/green: invalid/private/credential URLs reject without transport; unavailable
  response returns safe retryable503; app missing safe404/nonretryable. Failed key is
  not stored as success, so same-key Retry after recovery works without data loss.
  Fetch opens no shared write lock; successful source publishing/idempotency atomic.

## Task 2: editable seed and existing Analyze continuity

Extend `backend/tests/integration/test_steam_import.py` using existing Analyze service
and HTTP fixtures in `test_library_v2_analysis.py` / `test_analyze_vertical_slice.py`.

- [ ] Red: create manual Game withoutSteam; import with selected UUID/revision binds
  same UUID, keeps manual fields/reference IDs. Stale revision or another boundSteam
  returns409. Existing analyzedGame import refreshes onlysource, never removes analysis.
- [ ] Green: reuse Library identity checks; preserve manual business Steam overrides
  independently from source_identity. Explicit source URL wins only for binding,
  not as an implicit overwrite of human-entered fields.
- [ ] Red/green: source import→P2 PATCH→existing reanalyze job→real pipeline fixture
  publication returns originalUUID, keeps manual edits, and only full Analyze sets
  last_analyzed_at. No new queue/pipeline during source parse.

```python
assert imported['id'] == manual_game['id'] == analyzed_profile_id
assert final_detail['description'] == 'Human edit'
assert final_detail['last_analyzed_at'] is not None
```

## Task 3: bounded acceptance

- [ ] Format, export OpenAPI and add one operation to existing contract allowlist.
- [ ] Run focused Steam/import/Library/currentAnalyze regressions then complete
  realRedis suite in isolated fmg-v2-tests, one DB run at a time.
- [ ] One read-only integrated review, verified normal-flow blockers only; fix using
  red→green and final regression, no second broad review.
- [ ] Document `docs/backend-v2-steam-import.md`, exact test evidence and safe local
  commit; root/frontend notified of typed contract. Continue remaining Analyze handoff.

Self-check: explicit source-only fetch, editable source/manual split, same identity,
ordinary failure/retry, analyzed-data preservation and pipeline continuity covered.

## Execution evidence

All three tasks implemented. Initial source-only endpoint regression failed405 before
implementation, then focused47passed (14new import tests). Import→PATCH→jobs→actual
GameAnalysisPipeline/Service with offline providers publishes the sameUUID and retains
human/reference layers. One integrated read-only review: no blockers; conditional/error
OpenAPI annotations are deferred minor. Final export and full isolated realRedis suite:
**2296 passed / 3 deferred skipped / 0 failed**, 214.91s, 2026-09-08, one existing
Starlette warning. No migration (head0018), provider/model/SMTP, push or deployment.
