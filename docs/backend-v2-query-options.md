# P4/P12 read-query contract

## Scope and compatibility

Implements the filter/sort menus in original PRD revision751, P4/P12.1/P12.2.
Read-only extensions; migration head stays0014. No acquisition, evaluation, human
selection, profile mutation or email is triggered by these queries. Named saved
candidate sets are a separate subsequent unit.

Filtering and sorting operate on the complete bounded query/Library result before
pagination; `total` is the filtered total. Missing numeric/date values sort last,
with deterministic ties. Existing default orders remain for old clients; the new
frontend must explicitly request the PRD default.

## Candidate results

`GET /api/v2/discovery/queries/{query_id}/results`

- `evidence=all|current_game|reference_game|related_content|none` (default `all`).
- `sort=added|relevance|followers|recent_publish|recent_added` (legacy default
  `added`; new UI default `relevance`).
- Existing `limit`/`offset` remain. Rows add `evidence_groups` and
  `relevance_status=available|stale|not_evaluated`.

Recorded evidence requires both an excerpt and verification notes on a work for
the current account identity. `current_game` uses its explicit `game_id`;
`reference_game` uses its declared `work_name`, matched exactly after case folding
against the query's frozen reference names. `related_content` means **other recorded
content evidence outside those two groups**: it does not establish relevance to
the promoted game, actual gameplay, or that the sender watched it. UI labels/source
notes must preserve that distinction. There is no extra Match Brief requirement.
Title-only matches and missing evidence remain `none` (unknown, not “never played”).
Historical identity works do not classify a rebound account. Multiple groups can
occur across works.

Relevance uses only scores from the latest existing completed evaluation whose
current fingerprint remains valid. It neither starts an evaluation nor exposes
numeric ranking. Missing/stale values follow valid scores; ties use original
candidate ordinal and ID. For other sort modes relevance is not loaded, so the
status is `not_evaluated`, not an assertion that no evaluation ever existed.
`selected` remains the legacy false projection; explicit human selections still
come from the accepted selection API. Sorting/filtering does not alter them.

## Creator Library

`GET /api/v2/library/creators`

- Repeated `platforms` and `languages` parameters: OR within a field, AND across
  fields. Legacy singular `platform`/`language` remain and union with plural values.
- All four platform identifiers remain filterable, irrespective of connector
  implementation. Language comparisons now recognize the15 explicit code/name
  presets described in [language filters](backend-v2-language-filters.md); custom
  labels keep trimmed case-insensitive equality without storage changes. Omit
  languages for unrestricted; country is independent.
- `sort=name|relevance|followers|recent_publish|recent_added`; legacy default
  `name`, new UI `relevance`. Library relevance is search identity relevance
  (exact name/handle/account, then substring, then work-title match), not game fit;
  without search it falls back to deterministic name order.
- Rows/detail add `created_at`, `updated_at`, `latest_published_at`, up to three
  current-identity `recent_works`, `active_email_count`, and `contact_status`.
  Contact status only indicates active current email availability; it is not
  sending qualification or SMTP readiness. Updated time includes current works
  and active contacts. Existing keyword search covers name/account/current works.

## Game Library

`GET /api/v2/library/games`

- `website_status=all|available|missing`, default `all`.
- `sort=name|recent_updated|recent_added`, legacy default `name`, new UI default
  `recent_updated`. Rows/detail add `created_at` and `updated_at`.
- Website presence uses the already accepted effective `website_url` projection,
  including its existing source/canonical fallback. An explicit cleared manual
  override remains missing. Incomplete records stay visible in `all`.
- Existing keyword search covers game name/developer/ID.

## Verification

TDD: five new Library tests and seven new candidate tests first failed against
the prior implementation, then passed after implementation. Includes full-set
filter/total/sort before paging, current-identity summaries, website presence,
title-only evidence exclusion, existing/stale evaluation ordering, no side effects
and invalid enum rejection. Full regression and one bounded independent review
are recorded below.

Full isolated PostgreSQL17/Redis7 regression: **2152 passed, 3 skipped, 0 failed**,
169.34s. The three skips are the already approved old-live-writer migration cases;
one existing Starlette deprecation warning remains. Generated OpenAPI and Black
checks completed. One independent read-only integrated review found no blocker.
Deferred coverage suggestions: singular/plural union combinations, multiple groups
on one creator, and exact sort ties; inspected logic handles these cases. No real
provider, model, email or deployed stack was used.
