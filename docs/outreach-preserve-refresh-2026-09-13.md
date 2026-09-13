# Preserve personalization while refreshing recorded evidence

`POST /api/v2/outreach/drafts/{id}/refresh` accepts an optional
`preserve_values: true` plus an explicit `values` object containing all four
`firstName`, `channelName`, `reference`, `observation` strings. Empty strings are
allowed under the existing draft-value validation rules. Missing values or values
without preserve mode are rejected. Existing requests remain compatible.

Use a fresh composition GET for `expected_revision` and `context_token` after
updating the shared Library work and, if needed, the selection's work IDs. Keep
unsaved text in the client and send those values explicitly; never replace that
buffer with an old draft snapshot. A stale revision/context returns 409; read back
before retrying, including after an uncertain response.

Preserve mode atomically updates the source/fingerprint, stores exactly the four
submitted strings as values and manual overrides, increments the revision, and
clears sender facts and any old generation lease. A complete draft becomes
`succeeded`; a partial draft becomes `needs_repair`. Neither dispatches a model.
This changes only the target draft, not other drafts or frozen recipient history.
It does not confirm viewing or authorize SMTP sending.

TDD and isolated PostgreSQL/API integration cover generated drafts without
overrides, unchanged/unsaved/empty values, shared work PATCH, stale context,
response-loss readback, sibling preservation and zero broker dispatch. Existing
refresh, worker late-publication and sender-qualification regression are retained.
One bounded independent review passed. No database migration is needed.
