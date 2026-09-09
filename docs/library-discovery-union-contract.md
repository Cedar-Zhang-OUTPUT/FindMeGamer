# Library + live discovery (internal Demo)

## Client contract

`PlanCreate.platforms` accepts one to four unique values: `youtube`, `x`,
`twitch`, `instagram`. Existing request paths and fields remain; no client source
selector is required. Planning output queries and provider_queries support the
same four values. Selecting a platform always includes its saved Library records.

Live collection is separate. Existing collection settings expose `implemented`,
`enabled`, `credentials_configured`, `availability`; configured is not a guarantee
of live success. Twitch/Instagram remain selectable with unavailable live APIs.
Turning collection off does not turn Library discovery off.

`QueryView.sources[platform]` preserves existing live `status`, `blocked_reason`,
`issues`, coverage and usage. It adds:

```
library: {
  status: "more" | "complete",  // missing before the first scan
  scanned_count: number,        // cumulative Library rows scanned
  added_count: number           // cumulative unique candidates added by Library
}
```

Clients may represent missing initial state as pending, but must poll based on
query queued/running, not pending alone. Internal Library page/batch cursors never
leave the server. `more` allows explicit Continue even when live collection is
disabled, unavailable, failed or out of request/scan budget. The common result
limit still applies. Library-only completion has batch reason `library_only`,
while the platform's live status remains `not_supported`; it is not a live success.
`library_more` means the current bounded Library page ended with rows remaining.
Missing credentials and provider failures remain explicit paused/source states;
available Library candidates can still be evaluated.

Candidate shape/endpoints and evaluation remain shared. Optional
`filter_notes.discovery_sources` contains `library`, `realtime`, or both. Candidate
IDs and ordinals remain stable when the same platform/account reappears. Do not
equate discovery metadata with evidence that somebody played or watched a game.

## Runtime boundaries

- Library membership is bounded to records created no later than query creation.
  Explicit Continue walks a durable per-platform keyset cursor; new live imports
  do not create a self-feeding Library scan. Repeating the same batch does not
  scan the Library page twice.
- Each platform scans at most200 saved rows per batch, with a fair share of the
  batch candidate target. Metadata filters use the same effective/manual values
  and unknown policies as live results. Game relevance remains unified evaluation,
  not an invented keyword-to-played fact.
- The first eligible live page per platform is not suppressed merely because
  Library results filled the target. Existing indivisible-page behavior can exceed
  the soft batch target, but never the configured result limit. Paid request/scan
  ceilings remain unchanged; Library scans have separate bounded counters.
- Source failure and collection switches do not erase earlier candidates or
  other platform results. Existing uncertain-outcome acknowledgement semantics
  remain; there is no automatic paid retry loop.
- Library reads do not update Profile facts/works or pretend their collection time
  is the query time. URL-only records use an internal `library:<creator UUID>`
  Activity identity, not a fabricated provider account. Their public provider ID
  remains null. A real rebind increments revision and invalidates old snapshots;
  pending delivery protection also covers this internal identity.

No migration, new service, Instagram/Twitch API, SMTP send, default-selection
mutation, Campaign brief or template change is part of this unit. Initial default
selection requires its own persistent marker unit; clients must not implement it
by repeatedly bulk-adding on mount (which reactivates manual cancellations).

## Verification

New Library union, four-platform and budget regression tests were observed failing
before implementation. URL-only identity consistency also failed before its small
shared identity helper. Real database tests cover unsupported/disabled sources,
Library/live dedup, bounded append, shared filters, failed/missing live source plus
another successful source, four-platform API publication, safe public counters,
Profile preservation, and URL-only evaluation/preparation.

One bounded independent read-only review accepted the unit. Existing cross-query
selection regression now explicitly selects the matching account instead of using
an unordered scalar that assumed only one live candidate. Its dedup assertion is
unchanged. No production data or existing frontend fixture was changed.

Final focused gate: **143 passed**, one existing Starlette/AnyIO deprecation
warning. This covers planning/contracts, union/runtime/collection, API/evaluation,
preparation/rebind, candidate options and saved sets; not a redundant full backend
suite. The planning log assertion explicitly re-enables its logger in the test
because Alembic fileConfig disables preimported loggers in combined test runs.
