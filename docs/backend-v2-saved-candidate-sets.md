# Named candidate sets (P4)

Implements original PRD revision751, P4 “保存名单 / 修改条件”. A named set is an
immutable explicitly supplied subset of one existing discovery query, not an
outreach selection, a new query, or a permanent Profile version. Existing Activity
and query context/progress remain authoritative and unchanged.

## Four authenticated operations

| Operation | Request / response |
| --- | --- |
| `POST /api/v2/discovery/queries/{query_id}/saved-sets` | `Idempotency-Key`, body `{request_id, name, candidate_ids}` →201 `SavedSetView` |
| `GET /api/v2/activities/{activity_id}/saved-sets` | `limit`1..100(default50), `offset` → newest-first `SavedSetPage` |
| `GET /api/v2/discovery/saved-sets/{set_id}` | `SavedSetView` for reopening the original query |
| `GET /api/v2/discovery/saved-sets/{set_id}/results` | `CandidatePage`, same five evidence filters/four PRD sorts plus legacy `added` as the original query results |

`SavedSetView` includes `id`, `query_id`, `activity_id`, trimmed `name`, ordered
deduplicated `candidate_ids`, `count`, and `created_at`. Supply1..600 candidate IDs,
all belonging to the URL's query, and a nonblank1..255-character name. Invalid
membership is rejected atomically with422; no partial saved set remains.

Reuse both the HTTP key and client `request_id` when the response is uncertain.
The persistent request ID also prevents duplicate creation with a fresh HTTP key
or after HTTP replay retention expires; a changed request with the same ID returns
409. Different explicit saves may have the same display name; IDs distinguish them.

## Restore and selection boundaries

The metadata retains exactly the chosen membership even after more candidates
arrive. `/results` projects current Creator information for those original
candidates, with existing identity-change/stale-evaluation checks. It filters and
sorts the entire saved subset before pagination; its `total` reflects that filter,
while metadata `count` stays the saved membership count. Metadata preserves input
ID order; result order follows the requested sort (legacy default original query
ordinal, new UI should explicitly request `relevance`). Evidence semantics remain
those in [query options](backend-v2-query-options.md), including “unknown” and
other recorded content not being proof of relevant gameplay or sender viewing.

Restoring means reading metadata/results and reopening `query_id`; it does not
copy a query or mutate its conditions, source snapshots, cursor, provider state,
loaded count or batches. Late arrivals stay outside the saved set. Changed search
conditions still create a separate query through the existing API, retaining the
old query for later reopening.

No restore API starts acquisition, evaluation, analysis, human selections or email.
Use the separate explicit selection API if the user wants to add saved members
to an outreach list. No implicit “select all” or sending authority is inferred.
Rename/delete/history management is not added by this unit.

## Storage / verification

Migration0015 adds only `saved_candidate_sets` with a query foreign key, unique
persistent request ID/hash, name, UUID membership JSON array and timestamps.
Existing query/candidate/Profile data are not rewritten. The normal maintenance
window is sufficient. Downgrading populated named-set storage fails explicitly
instead of silently dropping saved lists; back up before any deliberate removal.

TDD: seven HTTP tests first failed on absent routes; the migration test first
failed on absent storage after correcting its fixture. Eight focused tests then
passed, exercising retries, query isolation, late arrivals, full-set filtered
pagination, identity rebinding, auth, input rejection and0014 upgrade preservation.
One bounded read-only integrated review found no blocker. The only deferred minor
is directly asserting candidate/settings preservation in the migration fixture;
the migration only creates the new table/index and the fixture already verifies
query preservation. OpenAPI allowlist and single-linear-head assertions were
updated for the four new routes and0015; the focused set plus these contract tests
passed19 tests. Full isolated PG17/realRedis regression: **2160 passed, 3 skipped,
0 failed**,193.70s; one existing Starlette deprecation warning. The three skips
remain the approved old-live-writer migration cases. The upcoming language-alias
unit's uncommitted red-test file was explicitly ignored and is not part of this
commit or its claim. No provider/AI/SMTP/deployed stack was used.
