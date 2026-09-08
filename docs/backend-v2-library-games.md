# Editable Game Library — first backend unit

Status: first backend unit verified (2026-09-08). No production
migration, deployment, provider calls or real emails are part of this unit.

## Scope and API

This unit adds manual games and human/source layering to the existing shared
Library. It is not the completed v2 discovery, activity or outreach workflow.
The authoritative schema is `backend/openapi.json`.

All four endpoints use the existing Workspace Bearer authentication:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v2/library/games` | Search and page the shared game library |
| POST | `/api/v2/library/games` | Create a manual game |
| GET | `/api/v2/library/games/{game_id}` | Read effective fields and provenance |
| PATCH | `/api/v2/library/games/{game_id}` | Edit fields, references and favorite |

List parameters: `query`, `only_collection` (false), `limit` (50, maximum 100),
`offset` (0). Response: `{items, total, limit, offset}`. Search matches effective
name, developer, Steam ID and website; sort is effective name/website, then UUID.

Create requires a name or HTTP(S) website. Other fields are optional:
`steam_app_id`, `developer`, `description`, `tags`, `languages`, `release_date`,
`cover_url`, `favorite`, `reference_works`. URLs may not embed credentials.
Creating a game does not start a provider analysis job.

POST requires a unique `Idempotency-Key` (8–128 characters, letters, digits,
period, underscore, colon or hyphen). Reuse it only when retrying the same save.
Within the 24-hour retention window the same request returns its original 201
snapshot; different input with the same key returns 409. Reload detail to obtain
subsequent edits rather than treating a replay as current state.

PATCH requires `expected_revision` from detail. Omitted fields are unchanged;
`null` clears a scalar, `[]` clears a list. `reset_fields` removes selected human
overrides and resumes source values. A field cannot be set and reset together.
Concurrent stale edits return 409; the UI should reload and let the user resolve
the conflict, not blindly retry with the new revision.

References are a full-list replacement of
`{id?, name?, url?, similarities: [], reason?}`. Each needs name or URL. Preserve
returned UUIDs when editing. Duplicate Steam identities, normalized URLs or
case-insensitive name-only references collapse to one entry. Removing a
reference does not delete a Library game. Per-activity reference selection will
be a separate contract.

## Source identity and human edits

Detail returns effective fields plus `source_fields`, `manual_overrides`,
`overridden_fields`, `source_identity`, revision and analysis timestamps.
Automatic analysis updates source data; successful and failed reanalysis must
not overwrite human fields or references. A failed analysis preserves the last
successful source result as well.

`source_identity` is the acquisition binding, not an editable display field.
Editing a game's website or business Steam ID does **not** silently rebind old
analysis jobs to a different game. A new game created with a Steam ID is initially
bound to that Steam source; its first actual analysis reuses the game UUID.
An unbound game created without a Steam ID remains unbound even if its business
Steam field is later edited. Explicit source rebinding is not implemented in
this unit; the UI must not promise otherwise.

The old v1 API remains usable for acquired/bound games. Unbound manual games are
v2-only and are rejected by the old Match flow. The new activity/matching flow,
Creator editing and multi-platform discovery are later units. This unit does
not implement draft invalidation/synchronization for the new outreach workflow.
Existing sent snapshots and response links are not changed.

## Errors and migration

Errors keep the existing `{error: {code, message, retryable, correlation_id}}`
envelope: 401 `workspace_key_invalid`, 422 `request_invalid`, 404
`game_not_found`, 409 `game_revision_conflict`, `game_identity_conflict`, or
`idempotency_key_conflict`.

Migration `20260908_0008` upgrades the released `20260904_0007` schema in a
maintenance window. It makes the source Steam ID nullable and adds human fields,
reference works and manual revision without changing existing profile UUIDs or
source payloads. Downgrade refuses to discard new manual data; restore a verified
pre-migration backup if reverting after users have created/edited that data.

## Verification

Use an isolated Compose project, never the live local or production database:

```sh
docker compose -p fmg-v2-tests -f backend/compose.test.yaml up -d postgres-test redis-test
docker compose -p fmg-v2-tests -f backend/compose.test.yaml run --rm --no-deps test pytest -q --tb=short
```

The suite exercises auth, validation, idempotency, revision conflicts, references,
source/manual layering, successful/failed reanalysis, first-analysis UUID reuse,
old API behavior and migration from the current release. Provider responses in
these tests are fixtures, not live API acceptance results.

Final verification: **1,854 passed, 3 skipped** in the full backend suite. The
three opt-in real Redis tests were then enabled against the same isolated Redis
and all **3 passed**, covering 1,857 distinct backend tests overall. The only
warning was the existing Starlette/AnyIO deprecation. Two frontend harness
configuration tests and six authenticated real HTTP checks also passed.

Independent bounded review found one ordinary interaction defect (URL-only games
were not searchable by URL); its regression test was observed failing, then
passed after the fix. Full regression also caught a legacy Game reuse case and
old migration-head assertions, both corrected. Four existing Creator resume test
failures were caused by a fixed clock earlier than database-created jobs; only
that test module's new-job clock was aligned, without weakening production
state validation or changing Creator logic.

To rerun the opt-in Redis checks:

```sh
docker compose -p fmg-v2-tests -f backend/compose.test.yaml run --rm --no-deps -e REAL_REDIS_URL=redis://redis-test:6379/0 test pytest -q tests/integration/test_job_dispatch_api.py::test_real_redis_broker_publishes_only_the_canonical_job_id tests/integration/test_redis_rate_limit.py::test_real_redis_counter_atomically_increments_and_preserves_first_write_ttl tests/unit/outreach/test_rate_limit.py::test_real_redis_atomically_limits_a_cross_process_burst
```

For frontend HTTP integration, see `integration/README.md`: the separate
`frontend_local.py` starter supplies persistent synthetic Game/Creator fixtures
on `http://127.0.0.1:18090`, with a private random test Workspace Key, dedicated
database and no Worker/Beat or provider/SMTP configuration. Do not reuse live
credentials. This fixture server is for Library/Settings integration, not proof
that new discovery or outreach workflows are complete.
