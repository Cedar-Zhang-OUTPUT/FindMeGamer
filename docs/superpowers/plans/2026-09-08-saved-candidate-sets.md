# Named candidate sets implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline with TDD and
> one bounded independent integrated review. Backend ownership only.

**Goal:** Save and restore explicitly chosen, named candidate subsets without
mixing queries, restarting discovery, or altering human outreach selections.

**Architecture:** One immutable named-set row references its original query and
stores an ordered deduplicated array of candidate UUIDs. The query already retains
conditions, source/account snapshots and progress; do not copy permanent Profile
versions. Read results through the existing full-set query projection constrained
to frozen membership. A durable client request UUID prevents duplicate saves.

**Tech Stack:** FastAPI/Pydantic/SQLAlchemy/PostgreSQL JSONB, migration0015.

**Spec:** PRD revision751 P4 `doxcnkbXL4bsv7Uj1blrISCRyAd`, reread original full
enclosing page requirements/menu2026-09-08. Root explicitly queues named collection
as independent unit after P4/P12 read queries.

## Global constraints

- Internal stable Demo; maintenance-window migration, no old live writers.
- Explicit member IDs only, maximum600; late discovery arrivals do not join.
- Restore is read-only: query progress/cursors retained, no automatic selection,
  dispatch, acquisition, evaluation or mail. Modified conditions use existing
  new-query endpoint, never overwrite the original query.
- Existing identity-change guards and filters/sorts remain. Saving is not sending.
- No rename/delete/version-history subsystem; not in this unit's requirements.

## Task1: durable save and restore

Files: new `backend/app/db/models/saved_candidate_set.py`, migration
`backend/migrations/versions/20260908_0015_saved_candidate_sets.py`, schema
`backend/app/schemas/saved_candidate_set.py`, repository
`backend/app/repositories/saved_candidate_sets.py`, routes
`backend/app/api/routes/saved_candidate_sets.py`; register models/router in existing
`backend/app/db/models/__init__.py` / `backend/app/main.py`; extend existing
`candidate_page(..., candidate_ids=None)` with membership predicate only.

Interfaces:

```text
POST /api/v2/discovery/queries/{query_id}/saved-sets
  Idempotency-Key; {request_id: UUID, name: trimmed1..255, candidate_ids: UUID[1..600]}
  -> 201 {id, activity_id, query_id, name, candidate_ids, count, created_at}
GET /api/v2/activities/{activity_id}/saved-sets?limit=50&offset=0
  -> {items: metadata[], total, limit, offset}, newest first
GET /api/v2/discovery/saved-sets/{set_id}
  -> metadata (reopen query_id through existing query API for preserved context)
GET /api/v2/discovery/saved-sets/{set_id}/results
  -> CandidatePage; existing evidence/sort/limit/offset options, frozen membership
```

- [x] Red: save subset twice with same request, replay with a fresh HTTP key,
  reject changed payload, read via new authenticated client; verify one row.
  `assert replay.json()['id'] == saved.json()['id']`.
- [x] Red: append candidate to source query, save result contains only original
  UUIDs; wrong-query UUID rejected atomically; two query sets remain independent.
  `assert restored.json()['total'] == 2` and cursor/status unchanged.
- [x] Green: validate query membership before insert; request hash covers path/name/
  deduped IDs; lock/write pattern reused from Activity `_write`. Read contains
  no dispatch. Metadata stores IDs only, no permanent Profile copies.
- [x] Red/green: activity paging, trimmed name/invalid empty membership, auth,
  missing IDs404, filter before page inside subset, identity rebinding still flagged.
- [x] Red/green: upgrade populated0014 preserves query; new table
  available, explicit unsafe populated downgrade refuses data loss.

## Task2: verify and hand off

- [x] Generate OpenAPI with `python scripts/export_openapi.py` in isolated test
  container. Focused tests then single full suite with REAL_REDIS_URL configured.
- [x] One bounded read-only integrated review; only actual internal-Demo blockers
  need fixes. Record Minors for later, no scope expansion.
- [x] Write `docs/backend-v2-saved-candidate-sets.md`, mark test evidence, explicit
  path local commit, notify root/frontend; continue approved outreach queue.

Self-check: implements named save/list/read/restored subset and preserves original
query loading context; relies on accepted new-query isolation, not a second engine.

Verification:8focused/19withcontracts; full2160passed/3deferred/0failed193.70s.
One independent integrated review ready/no blocker; candidate/settings migration
assertion coverage deferred. Future language red-test file excluded from this unit.
