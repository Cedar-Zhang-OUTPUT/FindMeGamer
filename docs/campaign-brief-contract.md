# Activity Campaign Brief

## API contract

- Activity creation accepts optional `campaign_brief` (`string | null`, maximum 5000 characters after trimming). Empty text becomes null.
- Activity responses expose `campaign_brief` and integer `revision` (initially 0).
- `PATCH /api/v2/activities/{id}/campaign-brief` accepts `{campaign_brief, expected_revision}` and returns the updated Activity. Existing API authentication applies; no additional Idempotency-Key is required.
- A successful update increments revision. A stale revision returns HTTP 409 `activity_revision_conflict`. On an uncertain response, fetch current state before deciding whether to retry; do not overwrite local edits automatically.

## Snapshot and evidence boundaries

The brief belongs to one Activity, not its shared Game Profile. New discovery queries and search plans freeze the current brief. Editing it does not rewrite existing plans, queries or evaluations.

Planning and evaluation prompts treat the brief as campaign intent, not verified game facts or evidence that a creator played a game. Evaluation carries it separately as unverified `campaign_intent`; the verified game fact data remains unchanged.

A brief edit invalidates existing preparation context tokens. A new recipient batch freezes the then-current Activity context. Existing recipient batches and sent snapshots remain unchanged.

Suggested UI copy: “Applies to new searches; existing results retain their original brief.”

## Migration and verification

Migration `20260909_0020` follows `20260908_0019`. Existing Activities receive null brief and revision 0. The migration test checks preservation of Activity source data, Game identity and complete existing recipient-batch records.

TDD began with failing prompt/API assertions. The focused business gate passed 57 tests; its one new migration-fixture failure was corrected. The supplementary gate passed 77 tests; its remaining migration-fixture SQL binding failure was corrected. The final Campaign Brief unit/API/migration rerun passed all 5 tests. A single bounded independent review returned Accept. Existing Starlette/AnyIO deprecation warnings are unrelated.

This unit has not been deployed. The frontend-owned Library-union fixture at port 56257 does not include this endpoint and must not be upgraded in place.
