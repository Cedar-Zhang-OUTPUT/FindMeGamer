# Activity and durable Discovery API

This unit implements HTTP → Celery task → official provider adapter → atomic
database/Library publication, verified with fixture provider responses. It does
not claim live provider acceptance, AI relevance ranking, selection, or sending.

## HTTP contract

All endpoints require the existing Workspace Bearer authentication. Every POST
requires `Idempotency-Key` (8–128 characters, existing allowed character set).
POST retries must preserve the same path, key and complete JSON body. Records
last 24 hours. New Activity operations use a database-scoped namespace so access
key rotation does not change their identity; legacy Game behavior is unchanged.

| Method/path | Purpose |
| --- | --- |
| POST `/api/v2/activities` | `{name, game_id, reference_work_ids: []}`; returns 201 |
| GET `/api/v2/activities` | Paginated activity list (`limit`, `offset`) |
| GET `/api/v2/activities/{id}` | Frozen source snapshot and associated queries |
| POST `/api/v2/activities/{id}/queries` | Frozen `QueryCreate`; starts first batch, 202 |
| GET `/api/v2/discovery/queries/{id}` | Conditions, batches, state, coverage, usage |
| GET `/api/v2/discovery/queries/{id}/results` | Paginated unique candidates, discovery order |
| POST `/api/v2/discovery/queries/{id}/stop` | No body; stops later pages, retains results |
| POST `/api/v2/discovery/queries/{id}/continue` | `{acknowledge_unknown: false}`; next bounded batch |

Create/continue return `{query_id, batch_id, status}`. A queue-dispatch failure
returns 503 **after saving**; retry the identical request to dispatch the same
batch, not create another query. Simultaneous/late duplicate deliveries cannot
re-run an already claimed/applied page. A new query key with changed conditions
starts an independent result collection within the same Activity.

Game detail and explicitly selected existing reference objects are frozen at
Activity creation. Query creation copies this snapshot; later Library edits do
not alter the query's provider cursor meaning. No endpoint edits query conditions.
This snapshot is campaign context, not a permanent Profile versioning system.

### QueryCreate

`providers` is a nonempty list of up to four unique-platform DiscoveryRequest
objects from the preceding unit. Client cursors are rejected; the server owns
pagination. The provider's `query` is provider search syntax. Source hints remain
hints, never filter evidence. Unsupported Twitch/Instagram sources return an
explicit source status without making a provider call.

| Limit | Default | Maximum |
| --- | ---: | ---: |
| `batch_target` eligible unique accounts | 100 | 100 |
| `result_limit` per query | 600 | 600 |
| `batch_request_budget` HTTP requests | 20 | 40 |
| `batch_scan_budget` provider items | 1,000 | 2,000 |
| `total_request_budget` per query | 120 | 240 |
| `total_scan_budget` per query | 6,000 | 12,000 |

Limits must be positive integers. These are hard ceilings, not promised result
counts. A page is atomic and can overshoot the batch target by at most that page;
it cannot exceed `result_limit`. Providers are scanned in the frozen list order.
No full AI analysis is scheduled for every discovered account.

Request/scan budgets reserve the maximum page cost **before** network I/O. Known
actual usage is reported separately in `usage.requests_used` and
`usage.provider_items_received`; `usage.unknown_requests_reserved` counts pending
or uncertain calls, not confirmed provider charges. Reservations may be more
conservative than actual usage; there is no fabricated dollar estimate. Both
per-batch and total budgets prevent unbounded retry/crawl spending.

### Basic filters

`filters` accepts countries (ISO codes), languages (content language codes),
`follower_ranges: [{minimum, maximum}]` inclusive union, `contact` (`any`,
`available`, `missing`) and independent unknown flags:
`include_unknown_country`, `include_unknown_language`, `include_unknown_followers`.
Empty lists mean unrestricted, including unknown. Specific conditions exclude
unknown by default. A range must have at least one nonnegative bound and cannot
be reversed. UI presets translate to the PRD's exact inclusive ranges; preset
mode/cancel behavior remains a client responsibility.

`pending_country_labels` stores unconfirmed text labels without applying them as
country codes. Country comes from acquired profile facts or explicit Library
edits, never YouTube region hints, X location text or language. Content language
can come from acquired content/explicit profile data, not search hints. Missing
counts are not zero. Contact filtering uses current active valid stored emails;
`missing` means none available in this Library, not proof no address exists.

Each candidate includes filter notes and unverified evidence status. Keyword
hits are not proof a creator played the game. Gameplay/reference evidence-based
refinement and AI ranking belong to later units. Default result order is discovery
order; it does not claim an AI relevance score.

## Stop, failures and recovery

Stopped queries keep current and in-flight results in their own query. No later
page begins; there is no selection API and `selected` is always false. Continue
while a page is still in flight returns 409. Existing candidate IDs are reused
across pages/batches; new results append, never replace earlier results.

A durable page reservation has a five-minute lease. Duplicate delivery with a
live lease does no provider I/O. An expired or otherwise unknown outcome pauses
discovery. Read responses expose `requires_acknowledgement: true` and
`outcome_unknown`; only explicit continue with `acknowledge_unknown: true` can
retry within the remaining budgets. That retry may incur another provider charge.
There is no automatic retry of unknown paid requests. Late invalidated responses
cannot publish into a newer batch or advance its cursor.

Ordinary provider failures retain prior results. Explicit continue can retry the
failed source at its saved cursor after configuration/rate-limit recovery.
Exhausted sources remain exhausted. Per-source status/coverage/issues distinguish
missing configuration, unavailable platform, partial data and failures; neither
usage-probe success nor failure gates discovery. Unsupported sources never run.

## Shared Library and storage

Import uses existing platform/account identity and current identity revision.
Manual overrides, emails, successful AI analysis and verified evidence survive
metadata refresh. Unknown or older metadata does not erase known facts. Archived
rebound identities or ambiguous manual URL bindings are not silently rebound.
New works are unverified source records with stable platform/content IDs.

Candidate `account` preserves the acquired discovery snapshot; `creator` is the
current shared Library detail. `identity_changed` signals a subsequent rebind.
Consumers must not treat old candidate identity as consent to contact the new one.

Migration `20260908_0010` adds five tables without rewriting old Profile, Match,
Campaign or mail data. Use a maintenance window. Downgrade refuses to discard
populated Activity data; restore the pre-migration backup instead.

## Verification boundary

Tests use isolated PostgreSQL/Redis and HTTP fixtures with real gateways and task
functions. They cover authenticated HTTP, frozen sources, queue retry, duplicate
delivery/pages, stop/continue, unknown recovery, source failures, budget ceilings,
manual/analysis/contact preservation and 0009 migration. No live provider,
production deployment, actual email or frontend fixture rebuild is performed.

Final verification, 2026-09-08: **2,019 backend tests passed**, no skips, with real
Redis enabled in isolated `fmg-v2-tests`; one pre-existing Starlette/AnyIO
deprecation warning. This unit adds 46 cases: 10 HTTP integration, 13 runtime,
1 migration, 19 Library/filter and 3 input contract cases. Black checks pass for
19 changed Python files, and `git diff --check` is clean. The committed OpenAPI
is regenerated and its offline deterministic-export test passes.

Independent bounded review found one ordinary language-filter issue (`und`/`zxx`
treated as known); failing fixtures reproduced it and the fix passed. Final
review reports no unresolved in-scope blocker. Two extra test-only Compose
projects were removed; main test and coordinated frontend environments remain.
