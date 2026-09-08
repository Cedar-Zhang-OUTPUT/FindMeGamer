# P1.2 Steam source import

Explicit source-only import, local internal-Demo implementation. No migration or
new deployed service. Existing Game Analyze remains a separate explicit action.

```text
POST /api/v2/library/games/steam-import
Idempotency-Key: stable key for this Submit/retry
{url:"https://store.steampowered.com/app/1245620/...", game_id?:UUID,
 expected_revision?:integer} -> GameDetail (200)
```

Only canonical Steam HTTPS app URLs are accepted. The URL becomes a canonical app
ID; it is never fetched as an arbitrary URL. Existing SteamGateway reads its configured
store API using English/US parameters, bounded responses and no redirects. Name,
developer, descriptions, genres, languages, release date and cover are projected
through existing v2 Game fields. `tags` falls back to source genres, not Steam user
tags or invented AI labels. Missing optional fields remain empty for manual editing.

New source records have no artificial manual overrides, revision1 and no analysis
timestamp. `manual_revision1` retains the existing first-Analyze seed convention;
it does not mean source values were hand-entered. Repeated successful request keys
return their saved response without another Steam request. A new Submit uses a new
key and refreshes the same source Steam ID, not a duplicate Game.

Supplying `game_id` and its `expected_revision` together explicitly binds a selected
unbound Game. Existing bound Steam source cannot be changed through this endpoint.
Another Game owning/claiming the same Steam ID returns409. If a previously unbound
Game only has a manually edited business `steam_app_id`, select its UUID explicitly;
ordinary source import will not guess that this was source-binding authorization.

Source publishing preserves manual overrides, favorite, reference IDs, analysis,
brief, model/prompt metadata and last/next analysis dates. It updates current source,
canonical identity, source-import timestamp and effective sort name; it increments
revision once. Source refresh is not AI refresh. Use the returned UUID/revision for
P2 PATCH; do not resubmit parsed values as manual overrides. The full Analyze action
uses source_identity canonical URL and existing jobs API, and publishes to this UUID.

Input checks and successful-request replay occur before network. Fetch releases the
read transaction, then short final publication takes the existing shared write lock
and rechecks request identity, selected revision and Steam ownership. A concurrent
human edit can therefore return409 rather than being overwritten. Parallel requests
may perform harmless duplicate source reads, but final writes/replay remain atomic;
there is no model charge, analysis task or mail side effect from import.

Unavailable Steam returns safe retryable503; a nonexistent game returns404; unusable
upstream data returns502. A failed request does not save a success or clear existing
data, and same-key retry after recovery can succeed. The frontend retains the user's
link/draft/known UUID and offers Retry or manual entry. Changing the requested link
requires a new key; conflicting successful key reuse returns409. Workspace auth applies.

## Verification

Focused47passed:14new import tests plus existing Steam and v2 Analyze regressions.
New tests run real SteamGateway over httpx fixtures; source import→P2 PATCH→jobs API→
real GameAnalysisPipeline/Service with offline provider/model fixtures→v2 read verifies
same UUID, preserved manual/reference fields and true analysis timestamp only afterward.
No live provider/model/SMTP, credentials, push or deployment. One bounded independent
review returned no blocking findings. Final exported OpenAPI/full isolated realRedis
suite **2296 passed / 3 deferred skipped / 0 failed**, 214.91s, 2026-09-08; one existing
Starlette warning. The three old-live-Writer migration lock-order skips remain outside
maintenance-window scope. Deferred minor: OpenAPI lacks conditional paired-field and
explicit error-response annotations; runtime validation and this document cover them.
