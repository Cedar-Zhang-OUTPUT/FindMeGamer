# Activity recipient preparation implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with TDD and one
> bounded independent integrated review as explicitly requested by the user.

**Goal:** Persist human Activity choices, a single chosen current email, verifiable
preparation status, and immutable recipient-list batches without sending anything.

**Architecture:** Three new tables for selections, batches and batch recipients;
reuse Library effective fields/contacts/works and Discovery evaluation. Authentication,
DB-scoped idempotency and short global job-change locks reuse existing v2 writes.
No worker, new service, inference, provider calls or SMTP.

**Tech Stack:** Existing FastAPI/Pydantic/SQLAlchemy/PostgreSQL, Alembic0013.

**Spec:** docs/prd-review-2026-09-08.md sections4/5/8,
docs/backend-v2-activities.md, docs/backend-v2-evaluation.md, coordinator handoff.

## Global constraints

- Internal stable Demo; maintenance migration from current0012.
- Backend/contracts/docs only; no desktop/18090/real local stack/cloud changes.
- Preserve untracked PRD review; no push/deployment/SMTP/platform/model/Keychain.
- TDD, one bounded independent review. Only ordinary E2E/data loss or duplication/
  Profile overwrite/clear secrets or SSRF/current migration/colleague errors block.
- No four-slot generation, email-body freeze, sender confirmation or reply sync.

## Contract decisions

Selection created from a candidate belonging to any query in this Activity.
Unique Activity+platform+account ID, independent of model selection and other
Activities. Cancel is reversible (active=false, revision++), not deletion. Same
identity re-add retains preparation. Rebound identities never silently transfer
old preparation: cancel old row then explicitly add current candidate, clearing
contact/evaluation/work/name confirmation. Discovery and evaluation continue to
report model-selection false; Activity selection list is authoritative for humans.

Selected contact is one explicit current active syntactically valid address.
Store contact snapshot/fingerprint at choice; later change marks contact_changed
until user explicitly reselects it. No fallback to first/all contacts. Missing
contacts, evaluation, evidence or public-name confirmation remain checklist items.
No numeric rank or minimum fit requirement. Library remains the editing surface.

Preparation has a deterministic context_token derived from current identity,
effective name/creator data, contact choices, selected works, associated evaluation
and selection revision. Update requests require expected_revision and the token
the UI actually read; stale forms return409. Public name confirmation stores exact
name+identity fingerprint and time, only following explicit confirm_public_name=true.
It does not inherit a global confirmation across identity rebinding. Sender watched,
sender facts and send_ready remain false; missing later send requirements stated.

Freeze explicitly enumerated active selections with matching observed context,
including members with no chosen email. Preserve N members as required by original
P4/P6/P7; contact can be null or need repair. No implicit exclusion or forcing users
to finish evidence/email in P4. Conflicting observed revisions reject atomically.
Frozen does not mean sendable; current preparation can be repaired while the initial
snapshot stays immutable, and final actual address/content freeze is a later unit.
Batch has persistent client request_id for recovery even after24h idempotency expiry.
Same request_id+same payload returns the same batch; different payload409. Batch
snapshots never mutate; live validity checks report changed/cancelled/identity-changed
inputs. Recovery is explicitly editing live preparation without rewriting the initial
snapshot; a new explicit batch is optional. Duplicate addresses across chosen accounts remain explicit
repair items; future send qualification must reject duplicate-address sending.

## Objects and API

`ActivitySelection`: id/activity_id/creator_id/candidate_id, platform/account_id/
identity_revision, active/revision, contact_id/snapshot, evaluation_item_id,
work_ids JSON, name_confirmation JSON, timestamps. Unique(activity,platform,account).
`RecipientBatch`: id/activity_id/request_id/request_hash, created_at; unique request_id.
`RecipientSnapshot`: id/batch_id/selection_id, snapshot JSON, context_token;
unique(batch,selection). Snapshots include identity/contact/source versions and
preparation evidence, but no SMTP state or mutable Delivery link.

All authenticated; mutations POST+Idempotency-Key.
- POST/GET `/api/v2/activities/{activity_id}/selections`: `{candidate_id}` / paginated.
- POST same`/bulk`: explicit add_candidate_ids and/or cancel_selections with their
  expected revisions, at most600 each, atomically. Never select future arrivals.
- GET `/api/v2/activities/{activity_id}/selections/{selection_id}`: live preparation.
- POST same`/update`: expected_revision/context, optional contact_id (null clears),
  evaluation_run_id (null clears), work_ids, confirm_public_name boolean.
- POST same`/cancel`: expected_revision (allows removing obsolete identity).
- POST/GET `/api/v2/activities/{activity_id}/recipient-batches`: create explicit
  `{request_id, recipients:[{selection_id,expected_revision,context_token}]}` / list.
- GET same`/{batch_id}`: immutable recipients plus live source_changed/issues.

Preparation response typed identity/contact options/selected contact state, current
public name and own confirmation, selected work details, evaluation result including
stale/identity flags, missing_fields, context token, freeze_ready, send_ready=false,
pending_send_requirements. Missing evaluation is not a score-based prohibition.

## Task1: selection and preparation

Files create `backend/app/db/models/activity_outreach.py`,
`backend/app/schemas/activity_outreach.py`,
`backend/app/repositories/activity_preparation.py`,
`backend/app/api/routes/activity_outreach.py`; register main/models.
Tests `backend/tests/integration/test_activity_preparation.py`.

- [ ] Red: HTTP create returns201, same candidate through second Activity query
  returns same selection id, other Activity separate; cancel then re-add stable.
  `assert response.status_code == 201`; initially404.
- [ ] Green: unique selection writes and typed paginated reads under existing_write.
- [ ] Red: explicitly choose second of two emails, return exact purpose/source;
  no choice remains a frozen-list repair item; wrong owner/historical/inactive rejected.
- [ ] Green: preparation builder plus optimistic update/token, explicit clear.
- [ ] Red: public confirmation stays false absent action; changed name/identity
  invalidates; selected known evidence excerpts retained, unrelated/metadata not
  claimed as verified gameplay, evaluation from foreign Activity rejected.
- [ ] Green: attach existing evaluation and work IDs, honest missing_fields.

## Task2: immutable batches and recovery

Extend models/schema/routes; repository `backend/app/repositories/recipient_batches.py`.
Tests `backend/tests/integration/test_activity_recipient_batches.py`.
- [ ] Red: explicit recipient subset freezes chosen email or null, preserves all
  missing-email members as repair items; stale token rejects atomically; no automatic joins.
- [ ] Green: durable request ID + immutable child snapshots, no dispatch hook.
- [ ] Red: same key/replayed requestID stays one batch, changed request409;
  cancellation/contact/profile/work/identity edits never rewrite snapshot but
  invalidate live preparation, new explicit freeze recovers.
- [ ] Green: current validity projection, deterministic source fingerprints.

## Task3: migration, integration and delivery

Create `backend/migrations/versions/20260908_0013_activity_outreach.py` and
`backend/tests/integration/test_activity_preparation_migration.py`.
- [ ] Red/green:0012 upgrade preserves existing Activity/query/evaluation and
  old mail tables; new tables usable; single linear head0013.
- [ ] Update typed OpenAPI expected operations; regenerate existing exporter;
  run focused tests then full realRedis backend suite in fmg-v2-tests only.
  Command: `docker compose -p fmg-v2-tests -f backend/compose.test.yaml run --rm
  --no-deps -e REAL_REDIS_URL=redis://redis-test:6379/0 test pytest -q --tb=short`.
- [ ] One bounded independent read-only review, fix only substantiated blockers.
- [ ] Doc `docs/backend-v2-outreach-preparation.md`, ledger evidence, local unit
  commit; report safe point to current coordinator and original integration task.

Self-review: selection does not imply sending; email snapshots are explicit,
identity confirmation is version-bound, evaluation gaps visible without score gate,
recovery doesn't rewrite history. Entire scope is one ordinary preparation flow.

## Completion evidence — 2026-09-08

Tasks1–3 implementation and verification are complete. TDD regressions additionally
covered atomic late-invalid bulk rollback and preserving explicit recipient order.
The three new focused files passed31 tests. The full PostgreSQL/realRedis suite
passed2125 tests in153.02s, with only the existing Starlette deprecation warning.
One independent read-only integrated review returned ready with no substantiated
blocker; no second review or scope expansion. OpenAPI has nine typed authenticated
operations and migration head0013. Local safe-point commit follows these checks;
no frontend, actual stack, provider, SMTP, push or deployment changes were made.
