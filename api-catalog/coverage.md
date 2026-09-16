# Provider catalog coverage

Metadata captured 2026-09-15. These are read-operation candidates, **not a claim that every operation has been exercised with company credentials**.

| Provider | Registered | Generic JSON read transport | Extra user authorization | Unsupported |
|---|---:|---:|---:|---:|
| YouTube Data API v3 | 29 | 14 | 13 | 2 |
| X API v2 | 104 | 50 | 36 | 18 |
| Steam unkeyed Web API inventory + Store helpers | 47 | 42* | 0 | 5 |
| Twitch Helix (2026-09-16) | 76 | 24 | 47 | 5 |

*Two entries use a bounded Store helper instead of the generic raw-JSON transport: `store.search` and `store.recommendations`.

`simulated` means a registered endpoint uses the unit-tested generic transport, not that each endpoint has a dedicated mock or real test. `requires-authorization` means this release does not supply the necessary user-context OAuth; company API keys/app bearer tokens cannot replace it. `unsupported` covers stream/media/authentication/session-changing operations. Platform write methods are omitted entirely.

X Ads and separate Enterprise API products are outside this X API v2 catalog. Steam's unauthenticated GetSupportedAPIList omits key-only interfaces; a later authorized inventory refresh can extend coverage. Neither limitation is presented as full platform coverage. Steam Store `store.appdetails` is a separately labelled convenience endpoint inherited from the product's existing game import, not a formally guaranteed Steam Web API.

## Rebuilding

The Steam builder also registers `store.search` and `store.recommendations`. These are not official Web API guarantees. Search keeps the original payload in `data.upstream` and adds candidate App IDs/names/URLs without choosing one. Recommendations parse only similar-product cards from the public Store page, deduplicate IDs and exclude the selected game. Current cards lack actual names: `name=null`, `name_hint` is a URL slug; use appdetails for a verified title. No automatic per-result requests. Both helpers use fixed HTTPS Store paths, no redirects, a 2 MiB decompressed response limit, default English/US locale and source URL/time metadata. Empty recognized recommendation pages differ from unrecognized pages and HTTP failures. A signed-in user's recommendations/order can differ.

Download official metadata into local files, then run inside `agent-service`:

```sh
.venv/bin/python -m fmg_agent.providers.build_catalogs \
  --youtube /tmp/fmg-youtube-discovery-20260915.json \
  --x /tmp/fmg-x-openapi-20260915.json \
  --steam /tmp/fmg-steam-api-list-20260915.json \
  --output ../api-catalog
```

Sources are recorded in each generated JSON with SHA256 fingerprints:

- https://www.googleapis.com/discovery/v1/apis/youtube/v3/rest
- https://api.x.com/2/openapi.json
- https://api.steampowered.com/ISteamWebAPIUtil/GetSupportedAPIList/v1/

Catalog changes require inspection and tests before deployment. Source descriptions are reference data, not instructions for Agents or for the generator. Runtime does not download or execute API metadata. Full upstream schemas are retained for description; actual response payloads are not forced through these schemas.

## Transport decisions

Twitch catalog is generated from the official reference HTML with a source SHA256. An explicit allowlist enables public research reads plus User-token follower totals; other authorized/account-management reads are listed but blocked. Write endpoints are not registered. Request and response field descriptions are preserved, including selector relationships. Batch array values become repeated query keys, not comma-separated strings. Pagination uses `pagination.cursor` → `after`; inspect operation restrictions before paging (notably video-by-category vs user). Twitch `Ratelimit-*` headers map to the same CLI metadata, and 429 uses the reset timestamp. Successful standard Helix reads are estimated at zero marginal USD under current assumptions; this is not unlimited quota or an invoice.

Live verification through the new local gateway succeeded for getGames, getStreams, getVideos, getUsers, getChannelInformation, getChannelFollowers (total only), and getClips. Remaining enabled reads have transport/catalog tests, not a claim of live endpoint acceptance. Twitch secrets stay server-side; see agent-service README for persistent token rotation and single-process deployment constraints.

- Authentication query/header values are exclusively server-managed. Local `key`, `access_token`, callback and arbitrary host overrides are rejected before network access.
- Request parameters use documented locations. X query arrays retain comma-list encoding; Steam declared `name[0]` families accept subsequent indexed entries without flattening them. Steam service message parameters use `input_json`.
- Default one request/one page; no automatic server retry, pagination or quota-consuming probes.
- `data` is the upstream JSON, including unknown fields and partial-error arrays. `meta` carries request ID, cursor and available limits. Missing quota values are null, never “unlimited”.
- Redirects are not followed. Only registered HTTPS hosts and paths are usable; path traversal values are rejected.
- 429 and daily/balance exhaustion are distinct. Error text is sanitized, and HTTP diagnostic logs redact credential-bearing query strings.

## Verification boundary

Task 2 regression suite covers authentication, catalog generation, read-only routing, retained fields, missing required parameters, forbidden overrides, path traversal, credential logging, redirects, quota errors, Steam optional keys and indexed parameters. Real Steam `ISteamWebAPIUtil.GetServerInfo.v1` succeeded through the new transport using the developer's configured local proxy; direct local Steam connection timed out.

Server-side smoke on 2026-09-15 used this new transport in a one-off container, with company credentials loaded in memory from read-only SQL. The old API/Worker/Beat remained stopped. These three operations succeeded:

- YouTube `i18nLanguages.list`: `etag`, `items`, `kind` retained.
- X `getUsersByUsername`: `data` retained; rate-limit headers parsed (limit 300, remaining 299 at that moment, not a permanent quota promise).
- Steam `store.appdetails`: full game envelope keyed by app ID retained.

This is representative transport verification, not deployed-gateway or exhaustive endpoint acceptance. Generated operation status remains conservatively `simulated`; these specific live results are documented here rather than falsely promoting entire operation families.

Task B local verification on 2026-09-15: the new `call_store` implementation, using an explicit HTTP transport through the developer's existing HTTP proxy, found `LIMINAL: Within` (App ID 4952700) and extracted 54 unique non-self recommendations for App ID 570. These are point-in-time results, not stable counts. Nine new fixture tests cover multi-candidate search, preserved fields, invalid identities, deduplication, unknown/empty pages, HTTP errors, redirects and size limits. Compiled CLI → real loopback HTTP → simulated Steam responses passed. No credentials or model calls were needed, and the new service remains undeployed.
