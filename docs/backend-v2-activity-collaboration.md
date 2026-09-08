# P9: same-list invitations and collaboration

Internal-Demo local implementation, migration0018. No inbox sync, mail dispatch,
follow-up email, provider request, push or deployment is performed by this unit.

## Read contracts

```text
GET /api/v2/activities/{activity_id}/invitations
GET /api/v2/activities/{activity_id}/invitations/{selection_id}
GET /api/v2/library/creators/{creator_id}/invitations?activity_id=UUID
```

Lists return `items,total,limit,offset` (default50, max200). Activity lists accept
`sending_state`, `invitation_state`, `follow_up_state` filters; omit a filter for All.
Filter before pagination; stable selection-created/id order does not change when
business state changes. Creator lists default to all actual associated Activities;
optional Activity filters use real IDs. A Creator with no association returns empty,
and no GET creates an Activity or tracking record. Frontend keeps its own viewport,
selection and filter parameters when returning from the unified Creator detail.

Each row carries Activity id/name, selection/Creator IDs, saved account identity,
selected flag, display name, revision, sending/invitation/follow-up/cooperation state,
notes, actual sent date, sourced response history, original recipient memberships,
and final-send history. Current selection, frozen recipient input and final sending
snapshot are distinct. Membership records retain batch/member IDs and input order.
Final history retains composition/batch/draft/member IDs, qualification status,
exclusion reason and optional existing B DeliveryView including frozen email content.

All active selections and canceled selections with frozen or collaboration history
remain visible. A three-member batch with two eligible and one explicitly excluded
still has three P9 rows. Repeated preparation of the same account appends membership
history rather than duplicating the relationship or replacing old mail/replies.
ActivitySelection's Activity/platform/account uniqueness is the relationship key;
changing an email is not a new person. Same Creator in another Activity is independent.
Historical frozen Creator associations remain readable after explicit identity changes.

Sending states: `not_sent`, `queued`, `sending`, `sent`, `failed`, `unknown`.
Expired sending leases use B's unknown projection. `sent` means SMTP accepted or
explicit B resolution, not proven inbox delivery. Only a recorded sent date derives
`awaiting_response`; queued/failed/unknown without a reply remain `not_invited`.
Actual sourced manual response takes precedence as `accepted` or `declined`, never
from opens, clicks, model output, preview or another Activity's response.
An older Delivery explicitly retried after a newer definite failure takes precedence
while queued/sending/sent/unknown; the newest failure is only a fallback. History
remains ordered by final-batch creation, so it is not itself a state-priority list.

## Manual writes

Both endpoints require `Idempotency-Key`; reads expose the current revision (0 when
no tracking exists). An outdated revision returns409; repeating the same successful
header/body replays without appending another response.

```text
POST /api/v2/activities/{activity_id}/invitations/{selection_id}/update
{expected_revision, follow_up_state?, cooperation_state?, notes?}

POST /api/v2/activities/{activity_id}/invitations/{selection_id}/responses
{expected_revision, outcome:"accepted"|"declined", source_note, responded_at}
```

Follow-up values: `not_followed_up` (default), `follow_up_needed`, `followed_up`,
`no_follow_up_needed`. Cooperation values: `not_started` (default), `in_discussion`,
`collaboration_confirmed`, `in_production`, `awaiting_publication`, `published`,
`settled`, `closed`. Neither advances automatically from acceptance. Notes can be
cleared with empty string; explicit null or an empty update is invalid.

Manual responses require a nonblank source note and timezone-aware `responded_at`;
server `recorded_at` and monotonic relationship revision are separately retained.
Corrections append a new event, newest recorded revision first; old evidence remains.
An operator can record a real external response even without this app's SMTP history,
but this never creates a Delivery, fabricates `invited_at` or marks sending as sent.
No user-supplied source URL is fetched. Progress/notes cannot directly change reply
or transmission state. Canceling selection or continuing discovery does not erase
manual history or final email snapshots.

The existing Creator rebind pending-delivery check now also checks Activity queued/
sending deliveries for that Creator's current platform/account. It uses the existing
`creator_delivery_in_progress`409. Historical sent records do not permanently prevent
rebind; frozen old-account mail remains unchanged and visible.

## Verification

Focused22 passed including15new C tests and existing identity regressions. Tests use
isolated PostgreSQL and existing HTTP/model/provider fixtures; no actual SMTP/provider
calls. One bounded review found the older-retry/newer-failure projection case above;
its real B API regression failed before the minimal priority fix, then passed across
queued/sending/unknown/sent states. No B policy change or second review. Final full
suite: **2282 passed / 3 deferred skipped / 0 failed**, 203.96s, 2026-09-08,
one existing Starlette warning. The original reviewer subsequently checked only the
fix and confirmed its blocker resolved; no expanded review. The skips are the
already deferred old-live-Writer migration lock-order cases. Repeated per-member list queries are a
deferred performance minor, to optimize if actual Demo list sizes require it.
Migration0017→0018 preserves final-batch/settings data and refuses a populated
destructive downgrade. Maintenance windows are supported, not rolling old/new writers.
