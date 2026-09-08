# Outreach B: Activity qualification and frozen final sending

> **For agentic workers:** Use superpowers:executing-plans inline, TDD and one
> bounded integrated independent review. Begin code only after Outreach A acceptance.

**Goal:** P7 full-batch qualification and explicit final confirmation through a
socket-free SMTP-capture E2E, with actual Activity provenance and safe unknown outcomes.

**Architecture:** Keep legacy Match campaigns intact. Add dedicated Activity send
batch/delivery records referencing P6 composition, draft and recipient snapshot;
reuse SMTPGateway, configuration and shared Redis limiter. A deterministic current
qualification fingerprint binds actual eligible subset and explicit exclusions;
final confirmation atomically freezes immutable MIME inputs before dispatch.

**Tech Stack:** Existing FastAPI/Pydantic/SQLAlchemy/PostgreSQL/Celery, SMTPGateway,
Redis limiter. No new deployed service or credential store.

**Spec:** `docs/outreach-v2-implementation-handoff.md` P7 and ordinary failure cases;
`docs/backend-v2-outreach-drafts.md` supplies A's typed immutable inputs.

## Global constraints

- Internal stable company Demo, maintenance window allowed, no rolling migration.
- Full functional P7, but no actual SMTP/provider calls, deployment or push.
- Only actual E2E/data loss/duplicate operations/concrete safety/current migration/
  colleague-facing errors block. Minor/HA/multitenancy/dirty DB stay deferred.
- No fake MatchTask/Result or response token to satisfy old model constraints.
- New locked mode has no automatic CTA/tracking in preview or worker MIME.
- Explicit exclusions retain original N and their reasons. Zero eligible cannot send.
- Draft completion, email open/click and AI fit never imply sender facts or replies.
- SMTP accepted means `sent`, not final delivered. Uncertain submission is not retryable.

## Task 1: typed qualification and explicit exclusions

Files: create `backend/app/schemas/activity_sending.py`,
`backend/app/outreach/activity_qualification.py`,
`backend/app/api/routes/activity_sending.py`, and
`backend/tests/integration/test_activity_qualification.py`; register router in main.

Contract:

```text
POST /api/v2/outreach/compositions/{id}/qualification
  {excluded:[{draft_id:UUID,reason:str}]} ->
  {composition_id,qualification_token,total_count,eligible_count,repair_count,
   excluded_count,sender:{address,name,reply_to},members:[
     {draft_id,recipient_snapshot_id,status,missing_fields,exclusion_reason,
      recipient_email,subject,html,text,values,slot_sources,template_version_id,
      fixed_hash,revision,context_token,sender_facts}]}
```

- [ ] Red: use real A fixture with three members; two source-complete/current
  recipients and one explicitly excluded repair. No AI-ranking prerequisite or
  per-recipient preview-open requirement. Assert original N=3 and eligible=2.
  Duplicate address rows are repairable until an explicit exclusion removes one;
  never silently merge recipients. Test before/after source/name/work/email/Game/
  sender change; old token changes, source-stale remains repair until A refresh.
- [ ] Green: `qualify(session, composition_id, exclusions)` loads every A draft,
  current data and immutable version, validates hash/four bound slots/recorded
  observation/facts/current selected eligible email. Compute sender from existing
  settings and require stored SMTP credential/config without decrypting into DTO.
  Group only nonexcluded current addresses by casefold; all duplicates need repair.
  Return safe typed DTO; fingerprint deterministic current fields, no time-of-read.

Example essential test assertions:

```python
assert preview['total_count'] == 3
assert preview['eligible_count'] == 2
assert preview['excluded_count'] == 1
assert all('Choice=' not in member['html'] for member in preview['members'] if member['html'])
assert current_preview['qualification_token'] != old_preview['qualification_token']
```

## Task 2: frozen final-send records and durable request identity

Files: create `backend/app/db/models/activity_sending.py`, migration
`backend/migrations/versions/20260908_0017_activity_sending.py`, repository
`backend/app/repositories/activity_sending.py`, tests
`backend/tests/integration/test_activity_final_send.py` and
`backend/tests/integration/test_activity_sending_migration.py`; extend schemas/routes.

Model `ActivitySendBatch`: UUID, activity/composition FKs, unique request UUID/hash,
qualification fingerprint, all-member qualification snapshot incl exclusions,
created timestamp. `ActivityDelivery`: UUID, send_batch/draft/recipient FKs, unique
(batch,draft), recipient/address/From/Reply-To/template/hash/HTML/text/source/facts
snapshot JSONB, state queued/sending/sent/failed/unknown, attempt, lease and SMTP
timestamps, sanitized error, retryable bool, explicit unknown-resolution notes.

```text
POST /api/v2/outreach/compositions/{id}/send-batches
  Idempotency-Key + {request_id,qualification_token,excluded:[{draft_id,reason}]}
GET /api/v2/activities/{id}/send-batches
GET /api/v2/outreach/send-batches/{id}
POST /api/v2/outreach/deliveries/{id}/retry {expected_attempt}
POST /api/v2/outreach/deliveries/{id}/resolve
  {expected_attempt,outcome:'sent'|'not_sent',source_note}
```

- [ ] Red: qualification token conflict creates zero deliveries; valid final
  confirmation freezes exactly2 and all3 original member provenance. Replay same
  key/body/request after response loss returns same IDs; conflicting request409.
  Edits after freeze do not rewrite delivery HTML/address/From/Reply-To/source.
- [ ] Green: serialized final write recomputes qualification, rejects repair rows
  not explicitly excluded and zeroeligible, inserts batch+eligible snapshots in
  one transaction. Durable request replay runs before current qualification check.
  Dispatch after commit; broker503 replay dispatches same queued delivery IDs.
- [ ] Red/green migration0016→0017 preserves A rows/settings, refuses populated
  destructive downgrade. No old campaign schema or fakeMatch conversion.

```python
assert len(created['deliveries']) == 2
assert replay['id'] == created['id']
assert replay['deliveries'] == created['deliveries']
assert frozen_after_library_edit == frozen_before_library_edit
```

## Task 3: transport with explicit unknown-submission handling

Files: extend `backend/app/outreach/smtp.py`; create
`backend/app/workers/activity_send_tasks.py`; register Celery include; add tests
`backend/tests/unit/outreach/test_smtp_unknown.py` and
`backend/tests/integration/test_activity_send_runtime.py`.

- [ ] Red/green `SMTPUnknownOutcome(SMTPError)` for disconnect/timeout after entering
  `send_message`, distinguishing explicit SMTP response rejection from unknown.
  Probe/login/connect failures stay normal failure. No broad raw upstream text leaks.
  Adjust legacy worker to treat the new explicit error as non-auto-retry without
  altering its canonical legacy CTA path; retain a legacy captured-mail regression.
- [ ] Green new task `find_me_gamer.outreach.send_activity_delivery` claims queued
  row under lock, commits before network, verifies current sending account identity
  against frozen sender and uses latest password only. Shared SMTP rate limiter;
  deferred limiter claim does not call SMTP. Fixed Message-ID from delivery UUID.
  Construct EmailMessage directly from frozen subject/text/HTML, From/Reply-To/To;
  no response token derivation, renderer or markdown rewriting at send time.
- [ ] Red/green socket-free SMTPFactory captures two MIME messages through real
  API→dispatcher→worker→SMTPGateway, verifies decoded canonical HTML/hash and actual
  sender fields. Duplicate workers do not capture again. One pre-send connection
  error fails only that member and explicit retry succeeds; explicit refusal never
  becomes sent. Disconnect inside send_message storesunknown, capturecount1, no
  automatic retry; resolve with human source note required before not_sent permits
  later explicit retry. A stale sending lease is unknown, not automaticallyqueued.

```python
assert len(captured) == 2
run_duplicate_workers()
assert len(captured) == 2
assert unknown['state'] == 'unknown' and not unknown['retryable']
assert ordinary_retry_unknown.status_code == 409
```

## Task 4: bounded acceptance and handoff

- [ ] Format touched files, export OpenAPI, update declaredoperations and linearhead.
- [ ] Focused qualification/finalsend/transport/currentmigration/legacyregression,
  then full realRedis suite serially in `fmg-v2-tests`.
- [ ] One integrated read-only review, fix only verified blockers with red/green;
  root-owned fixture/handoff/ledger paths never staged.
- [ ] Write `docs/backend-v2-activity-sending.md`, exact verification results and
  explicit local commit; send root accepted contract. Proceed to C separately.

Self-check: P7 full preview, no per-person-open gate, explicit eligible subset,
immutable final snapshot, actual Activity source and safe unknown recovery are all
mapped above. P9 reply/follow-up is C; inbox sync and real SMTP validation remain out
of this unit. This plan is not evidence of implementation or test completion.

## Execution evidence

All four tasks implemented. Focused75 passed. The single integrated reviewer found
one legacy public projection omission for SMTP unknown; minimal safe enum/allowlist
fix and red→green regression completed, no legacy resend-policy expansion. Final
OpenAPI export succeeded; full isolated real-Redis suite **2267 passed / 3 deferred
skipped / 0 failed**, 221.26s, 2026-09-08, with one existing Starlette warning.
See `docs/backend-v2-activity-sending.md` for the delivered contract. Tests include
socket-free SMTP capture only, not real outbound delivery or deployed acceptance.
