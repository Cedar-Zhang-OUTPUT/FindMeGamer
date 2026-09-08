# Outreach C: same-list invitations and collaboration

> **For agentic workers:** Use superpowers:executing-plans inline as authorized,
> TDD and one bounded integrated independent review, after B's safe commit.

**Goal:** P9 and Creator Invitations & collaboration read/write the same real
Activity membership, sending history, sourced manual replies and business progress.

**Architecture:** ActivitySelection's unique Activity/platform/account identity is
the relationship key. Read selected members plus canceled members with preparation
or collaboration history; preserve every RecipientSnapshot and final batch member.
New versioned tracking and append-only response records never rewrite mail snapshots.
Reuse B's delivery projection including expired-lease unknown outcomes.

**Tech Stack:** Existing FastAPI/Pydantic/SQLAlchemy/PostgreSQL; no new service.

**Spec:** `docs/outreach-v2-implementation-handoff.md` §2 C, §5 P9, §6; root's ordinary
Creator identity guard integration instruction. B is a separate accepted boundary.

## Global constraints

- Internal stable Demo, maintenance-window migration; no deployment/live calls.
- No automatic inbox, follow-up email, resend-sent, click→acceptance or fake Activity.
- Follow-up: not_followed_up / follow_up_needed / followed_up / no_follow_up_needed.
- Cooperation: not_started / in_discussion / collaboration_confirmed / in_production /
  awaiting_publication / published / settled / closed. Both manually set, independent.
- Sending: not_sent / queued / sending / sent / failed / unknown. Invitation:
  not_invited / awaiting_response / accepted / declined. Unknown does not imply sent.
- Source note and timezone-aware response time required for manual accepted/declined;
  preserve recorded time and all corrections, never infer response from transmission.
- Stable creation order, pagination and filter parameters; read-only GETs create nothing.
- Same account across different activities is independent. C never edits selections,
  frozen recipients, discovery queries or final mail; cancellation retains history.

## Task 1: same-list typed projection

Create `backend/app/schemas/activity_collaboration.py`,
`backend/app/repositories/activity_collaboration.py`,
`backend/app/api/routes/activity_collaboration.py`,
`backend/tests/integration/test_activity_collaboration.py`; register router in main.

Interfaces:

```text
GET /api/v2/activities/{activity_id}/invitations
  ?sending_state=&invitation_state=&follow_up_state=&limit=50&offset=0
GET /api/v2/activities/{activity_id}/invitations/{selection_id}
GET /api/v2/library/creators/{creator_id}/invitations?activity_id=&limit=50&offset=0
```

Member fields: selection_id, creator_id, Activity id/name, selected, identity,
display_name, revision, sending/invitation/follow_up/cooperation state, notes,
invited_at, response history, recipient memberships and final-send references.
Membership keeps batch ID, RecipientSnapshot ID/input_order/snapshot. Final history
keeps composition/send-batch/draft/recipient IDs, qualification status/exclusion reason
and optional B DeliveryView. Full original N survives even without Delivery.

- [ ] Red: selection-only returns defaults, genuine empty Creator returns zero without
  creating Activity; B's three-member batch returns all3 with2 queued and1 excluded.

```python
assert page['total'] == 3
assert [r['sending_state'] for r in page['items']] == ['queued', 'queued', 'not_sent']
assert excluded['send_history'][0]['exclusion_reason'] == 'Need evidence'
```

- [ ] Green: select ActivitySelection in stable created/id order; include active OR
  existing RecipientSnapshot OR tracking. Join preserved snapshots and qualification
  members by RecipientSnapshot selection ID, not mutable email/name. Display original
  identity/frozen name when current Creator identity differs; Creator history includes
  historical snapshot.creator_id as well as current selection.creator_id. Derive latest
  effective sending state, sent date only from actual sent delivery; awaiting_response
  only after sent and absent manual reply. Return unknown separately. Filter before
  slicing so total reflects selected filters, never modify the list on read.
- [ ] Green check selection cancel, fresh preparation batch and identity rebind retain
  historical membership/mail; Creator Activity filtering returns real names/empty.

## Task 2: versioned manual relationship state

Create `backend/app/db/models/activity_collaboration.py`, migration
`backend/migrations/versions/20260908_0018_activity_collaboration.py`,
`backend/tests/integration/test_activity_collaboration_migration.py`; extend Task1.

Model `ActivityCollaboration`: selection_id PK/FK, revision0, four-state follow-up
default not_followed_up, eight-state cooperation default not_started, notes default
empty, timestamps. `ActivityResponse`: id, selection_id FK, relationship revision,
accepted/declined, source_note, responded_at, recorded_at; unique(selection,revision).
Reads project defaults without inserting. Source note is plain text, not fetched.

```text
POST /api/v2/activities/{activity_id}/invitations/{selection_id}/update
  Idempotency-Key + {expected_revision,follow_up_state?,cooperation_state?,notes?}
POST /api/v2/activities/{activity_id}/invitations/{selection_id}/responses
  Idempotency-Key + {expected_revision,outcome,source_note,responded_at}
```

- [ ] Red: two Activities sameCreator; accepted with source/time only changes first,
  defaults remain manual, notes/progress editing preserves acceptance, stale revision409,
  header replay adds no response, new correction appends history without deleting old.

```python
assert first['invitation_state'] == 'accepted'
assert second['invitation_state'] == 'not_invited'
assert first['cooperation_state'] == 'not_started'
assert corrected['responses'][1]['outcome'] == 'accepted'
```

- [ ] Green: existing `_write` global lock/idempotency; validate selection belongs to
  Activity, expected revision exact. Create tracking only explicit write, increment
  revision each accepted mutation. Manual response can document externally received
  invitations even without SMTP history; never manufacture sent date or Delivery.
  Every response stores original source/time plus server recorded_at. Notes/progress
  cannot directly edit invitation/sending state. No automatic progress transitions.
- [ ] Red/green: invalid enums, blank sources, missing/naive time, unauthorized/cross
  Activity writes reject; HTTP follow-up4/cooperation8 round-trip; read never changes
  revision. Migration0017→0018 preserves existing send history and settings; populated
  destructive downgrade refuses, empty downgrade works. Update head assertion0018.

## Task 3: current-account pending delivery guard and acceptance

Modify `backend/app/repositories/creator_identity.py`; test in
`backend/tests/integration/test_activity_collaboration.py`.

- [ ] Red: create B queued delivery; HTTP Creator rebind returns409
  creator_delivery_in_progress. Sending also blocks; sent permits legitimate rebind.
- [ ] Green: extend existing pending check to ActivityDelivery queued/sending whose
  frozen platform/account matches current Creator identity; no permanent ban from
  historical sent or another account. Keep old guard/error/locking behavior.
- [ ] Format, export OpenAPI, update operation allowlist; run focused HTTP/current
  migration then complete real-Redis suite serially in isolated fmg-v2-tests.
- [ ] One integrated read-only review, repair only verified normal-flow blockers;
  no second broad review or public-system hardening. Main verifies final regression.
- [ ] Add `docs/backend-v2-activity-collaboration.md` with contract/evidence, stage C
  paths only and commit; notify root/frontend then proceed approved Analyze queue.

Self-check: same N, two-Activity independence, sourced manual responses, four/eight
enums, Creator unified projection, stable filters and pending rebind guard covered.
Frontend rendering remains its thread; P9 does not add a new workspace or live inbox.

## Execution evidence

All three tasks implemented; initial missing APIs and pending-delivery rebind guard
failed as expected, then focused21 passed. One integrated review found newer failed
batch hiding an older explicit retry; real B API regression red→green, focused22passed
(15newC tests). Original reviewer did only the requested fix-check and confirmed the
single blocker resolved. Final exported OpenAPI/full isolated realRedis suite:
**2282 passed / 3 deferred skipped / 0 failed**, 203.96s, 2026-09-08; one existing
Starlette warning. No live provider/model/SMTP, push or deployment. Repeated per-member
list queries are deferred minor optimization, not a current internal-Demo blocker.
