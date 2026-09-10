# Local selection → Prepare contract

Checkbox/select-all/filter/pagination interactions change a client-side desired
candidate set only. They do not call selection mutations. A single **Prepare**
user action can reuse the existing APIs below; no new backend service or schema
is required. This is two ordered writes, not one cross-request transaction.

## Commit sequence

1. Snapshot the desired ordered candidate IDs and prevent conflicting local edits
   during submission. Retain this snapshot and transaction progress on failure.
2. Read all relevant Activity selections (`limit` at most 200; paginate to `total`).
   Let `A` be active candidates and `D` the complete desired set for the managed
   Activity scope. Hidden pages/filtered-out selections are not implicit removals.
3. If the difference is nonempty, POST `selections/bulk` once:
   `add_candidate_ids = D - A`; `cancel_selections = A - D`, each cancellation
   carrying its selection ID and expected revision. Never submit two empty arrays.
   The request supports up to 600 additions and 600 cancellations. It is atomic:
   one invalid cancellation/addition rolls back the entire delta.
4. Read current selections after the bulk acknowledgement. Resolve exactly `D`
   by candidate ID; retain the user's intended order. Verify every desired member
   exists, is active and has the expected current identity. Do not freeze all
   server-active members by default or silently re-add a concurrently removed one.
5. POST `recipient-batches` with a stable UUID `request_id` and explicit recipients:
   each has `selection_id`, `expected_revision`, `context_token`. The server checks
   revision and current preparation context before writing any batch/member.
6. On success retain the returned batch ID and continue to composition. Creating
   a recipient batch neither sends mail nor confirms names/viewing/evidence.

Freeze requires an active explicit selection, **not** complete outreach evidence.
Missing contact/name/work evidence remains repairable preparation data. The client
must not auto-confirm those fields merely to make a row appear ready. Preparation's
`freeze_ready` currently means active; inspect `identity_changed` as well rather
than treating that one boolean as complete source validation.

## Recovery rules

- Bulk and freeze each have their own stable `Idempotency-Key` and exact original
  payload. Save stage/key/payload before dispatch. A timeout or unknown 5xx outcome
  replays that same request, not a newly calculated delta or new key.
- Cached HTTP idempotency records last 24 hours. The freeze body's `request_id`
  additionally has persistent deduplication. `GET recipient-batches` includes
  request IDs, so the client can page the list to recover its known freeze intent.
  Persistent recovery guarantees the same batch and immutable snapshots, not
  byte-identical live preparation fields if source records subsequently changed.
- Reusing a key with changed data gives `idempotency_key_conflict`. Reusing a
  freeze request ID for a different list gives `recipient_batch_request_conflict`.
- After a definite revision/context rejection, re-read and explain the changed
  source. An explicitly resumed operation gets new request identity and context;
  do not silently replace the body of a still-uncertain request.
- If bulk succeeded but freeze failed, selections may already be committed.
  Keep local `D` and stage progress; do not clear checkboxes, repeat the entire
  workflow blindly, or issue compensating cancellations. Refresh context and
  resume freezing after resolving the error.
- A later colleague's selection write can occur between the two requests. The
  frozen list still consists only of explicit `D`, not every current active row.
  Revision/context validation protects the chosen members; no rolling-upgrade or
  distributed-transaction requirement is introduced for this internal Demo.

## Verification

`test_prepare_selection_commit.py` exercises the full existing HTTP contract:
final add/cancel delta, lost bulk acknowledgement without duplicate revisions,
lost freeze acknowledgement with one persistent batch, explicit recipient order,
source-conflict recovery preserving committed selections, and whole-delta rollback
on a cancellation revision conflict. The change adds contract tests/documentation,
not a production endpoint, model call or sending operation. The unchanged-selection
case also verifies that an empty bulk is skipped before direct freezing. Retention
of the local desired set is a client responsibility requiring frontend tests;
backend tests prove preservation of server selections, not browser state.

One bounded independent review found no backend blocker; the no-op case was added
following that review. No new backend business behavior is necessary for this
interaction. Final related PostgreSQL integration run: **34 passed**, no skips,
one existing Starlette deprecation warning.
