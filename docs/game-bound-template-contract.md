# Shared game-bound outreach template

## Catalog and registration

Existing paths remain: `GET /api/v2/outreach/template-versions?game_id=…` and `POST /api/v2/outreach/template-versions/canonical` with `{game_id}` and Idempotency-Key. This remains game-scoped through the Activity's `game_id`, not Activity-scoped.

The selected game's catalog builtin has key `game-outreach-v1`, five fixed fragments, four unchanged Creator slots (`firstName`, `channelName`, `reference`, `observation`), and SHA256 `fixed_hash`. Catalog without a game returns `builtin: null`. Registration deduplicates the rendered content hash per game; changed rendered facts produce a new immutable version. Existing versions remain readable, including historical canonical and user_saved records.

New arbitrary template creation returns 422 `template_creation_disabled`. New compositions accept only the current game-bound content hash; older or historical templates return 409 `template_context_changed`. Previously created compositions and sent snapshots are not rewritten.

## Metadata

For game_bound: `kind: game_bound`, `revision: 1` (template structure), `game_id: UUID`, `game_revision: integer`, `game_fingerprint: SHA256`, `steam_app_id: string|null`, `sender_name: string|null`. Compatibility fields `document_id` and `raw_hash` are null. Historical canonical/user_saved records retain their previous metadata; added fields are null.

## Facts and sender identity

Game name, website, description, and recorded reference comparisons come from that Game's effective source/manual Library facts. HTML text is escaped. Missing plot, gameplay, comparison, release/demo availability, or other facts are not inferred from LIMINAL, another Game, or Campaign Brief. Common invitation text remains fixed; AI fills only the four Creator slots.

Only configured SMTP `from_name` is used for the sender name. Unverified Toki/job title/company/location from the old example are not assumed. With no name, neutral previews, registration and drafting remain available, but qualification reports `sender_identity_missing` and cannot send. Missing SMTP additionally reports `smtp_not_configured`.

After changing the sender name or rendered Game facts, register the current template and create a new composition. Refreshing an old draft does not overwrite fixed text: `template_context_changed` remains a repair requirement. Do not repeatedly refresh that draft expecting its template to change.

The integration fixture uses an explicitly synthetic sender, never production identity or real SMTP. Production identity confirmation remains with the user.

## Verification scope

TDD covered game isolation, deterministic rendering/escaping, source changes and stale-composition rejection. Backend independent review returned Accept. Focused gates cover immutable historical versions, final qualification, immutable send snapshots and socket-free SMTP capture. Renderer verification is a separate frontend-owned step; no existing frontend fixture is upgraded in place.
