# Official discovery adapters — third backend unit

## Delivery boundary

This unit provides a provider-neutral Python page contract and official YouTube/X
adapters for the next Activity worker to consume. It does **not** introduce a
parallel Profile store, persistent discovery sessions, public search HTTP route,
automatic multi-page crawl, stop/resume workflow, AI analysis, or outreach.
Provider calls are verified with HTTP fixtures only. No live provider credential
or production data is used by this unit's tests.

## One-page contract

`app.schemas.discovery.DiscoveryRequest` accepts `platform`, `query`, `page_size`
(default 25), `cursor`, and `max_requests` (0–2, default 2). Query is provider
search syntax, not an AI prompt. YouTube additionally accepts `search_mode`
(`video` or `channel`), `region_hint`, and `language_hint`. Unsupported hints are
rejected rather than ignored. X page sizes are 10–100; YouTube 1–50.

A cursor contains an opaque provider `token` and a `query_fingerprint` binding
platform, query, page size, mode and hints. Continue with the original settings.
The fingerprint prevents accidental reuse; it is **not** an authorization token
or a signed tamper-proof cursor. Provider cursors can expire; no durable resume
guarantee is implied. Search result sets can change between calls.

`DiscoveryPage` contains:

- `accounts`: unique platform/account IDs, canonical profile URL, public name,
  description and optional metrics, source collection time, metadata completeness.
- `contents`: unique platform/content IDs, associated account ID when available,
  source URL, provider text/title, optional publication time and public metrics.
  `evidence_status` is always `unverified`.
- `next_cursor`: continue only when supplied; a short or empty page alone does
  not prove exhaustion.
- `status`: `complete`, `more`, `partial`, `failed`, `budget_exhausted` or
  `unavailable`; `issues` supplies safe categorical errors, not upstream bodies.
- `requests_used`, `provider_items_received`, `coverage`, and `estimated_cost`
  (null: no fabricated dollar/quota estimate).

No automatic retry occurs. A retry is another provider request and may cost
money. The request budget limits network requests, not provider dollar spend.
YouTube reserves a two-request budget before starting, and reports the actual
one or two requests used (no channel request when there are no channel IDs).
X needs one request. Insufficient budget returns without network traffic.
The future Activity layer must enforce total run/account/page/cost budgets and
deduplicate across batches by `(platform, account_id)` / `(platform, content_id)`.
Neither adapter promises to return 100 or 600 distinct creators.

The entry points are `YouTubeDiscoveryGateway(api_key=..., base_url=...)` and
`XDiscoveryGateway(bearer_token=..., base_url=...)`; use them as context managers
and call `.discover(request)`. The next server-side Activity layer must load the
encrypted connection using the existing SettingsRepository/SecretCipher pattern,
release its database transaction before provider I/O, and never accept a provider
base URL or secret from a discovery form. Both adapters accept an injected HTTP
client for fixture tests. Shared injected clients remain owned by their caller.

## Capability semantics

`platform_capabilities()` reports implemented capabilities, not credential status
or proof of a successful live request. YouTube supports discovery and the existing
analysis pipeline; X supports metadata discovery but not full AI analysis in this
unit. Both require a configured connection and provider permissions. Twitch and
Instagram are unavailable presets. Missing metrics remain null, not zero.

YouTube region is a video availability hint, not creator residence. Language is a
search relevance hint, not proof of creator language. X location is a public
free-text field, not a verified country. Search titles, post text and thumbnails
are not confirmation of gameplay or proof a colleague watched the content.

## X Settings

The existing authenticated endpoints accept service `x`:

- `GET /api/v1/settings/connections/x`: configured/test status only.
- `PUT /api/v1/settings/connections/x` with `{ "secret": "…" }`: encrypt and
  replace the Bearer token; clear previous test status. Never return saved secret.
- `POST /api/v1/settings/connections/x`: test the stored token against the official
  usage endpoint. A successful test means usage endpoint access, **not** verified
  recent-search permission, sufficient balance, or full analysis capability.

A failed usage probe similarly does not prove the token is invalid or recent
search is unavailable: usage can have different access requirements or a temporary
failure. `configured`, `last_test_status` and unverified search capability remain
separate. Do not gate future discovery runs on the usage probe's success/failure.

No client ID/secret or posting/DM authorization is required for this app-only
read adapter. No claim is made that a provider connection test is free.

## Future Library import

Use the existing CreatorProfile `platform` + `platform_account_id` uniqueness;
resolve the current identity generation and merge into source fields only.
Preserve manual overrides, contacts and evidence. Work identity uses the existing
CreatorWork `(creator_id, identity_revision, platform, source_content_id)` key.
Discovered accounts are transient metadata, not automatically committed Profiles.
Import/upsert transactions and Activity persistence belong to the next unit.

## Official references (checked 2026-09-08)

- [YouTube search.list](https://developers.google.com/youtube/v3/docs/search/list)
- [YouTube channels.list](https://developers.google.com/youtube/v3/docs/channels/list)
- [X recent search](https://docs.x.com/x-api/posts/search-recent-posts)
- [X recent-search guide](https://docs.x.com/x-api/posts/search/quickstart/recent-search)
- [X pagination](https://docs.x.com/x-api/posts/search/integrate/paginate)
- [X usage](https://docs.x.com/x-api/usage/get-usage)

YouTube search and channel enrichment are separate requests. X recent search
provides a seven-day search window and author expansion. Neither implies full
account history. Provider pricing, quota allocation and permissions are external
configuration and must be checked before enabling real runs.

## Verification

2026-09-08: isolated `fmg-v2-tests` full backend suite with
`REAL_REDIS_URL=redis://redis-test:6379/0`: **1,973 passed**, no skips; one existing
Starlette/AnyIO deprecation warning. The new tests include 29 YouTube adapter,
23 X adapter, 3 shared-contract, and 15 X connection/settings cases (70 total).
TDD red/green cycles were observed; the final 12 changed Python files pass Black
and `git diff --check`. Independent bounded read-only review found no in-scope
blockers. No live provider/search/credits validation or production deployment is
claimed. The existing stable frontend fixture service was not rebuilt or reset.
