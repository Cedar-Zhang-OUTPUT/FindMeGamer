# Steam Store recommendations → Reference Works

## Source and bounds

The existing Steam gateway now fetches the Store HTML page `https://store.steampowered.com/recommended/morelike/app/{app_id}/?l=english&cc=US` after successful base game acquisition. This is a best-effort Store-page adapter, **not a documented stable Steam Web API**.

Only `similar_grid_capsule` app links inside the first `div#released` are considered. Ignore the source app, duplicate identities, non-Steam hosts, non-app targets and subsequent Upcoming/Free/New/Top Sellers groups. Keep at most 9 IDs. Resolve each actual English name through the existing Steam appdetails mapping, with at most 3 concurrent requests and shorter per-request timeouts. Do not derive names from URL slugs or generate similarity reasons. Redirects are not followed; no scraped URL is fetched. Responses remain bounded.

Real read-only verification on 2026-09-10 returned 9 available recommendations for app 4952700, including Desktop Explorer (2527160), Halloween: The Game (3219630), Library Of Ruina (1256670), and Crow Country (1996010). This verification did not create or modify a production Profile.

## Persistence and user intent

Both synchronous Steam import and successful game analysis publication use the same merge. Existing manual/reference content is never overwritten or removed by source refresh, including successful empty results. Match by canonical Steam app identity. Append new recommendations within the existing 100-reference profile limit.

Operator deletion or retargeting records the removed Steam identity, including manually created references and edits before any recommendation fetch. Previously imported reference IDs are tracked so an edited source recommendation is not re-added under its old identity. Tombstones and source status live in the existing `GameProfile.source_status` JSON; no migration is required. Explicit user re-addition remains allowed; refresh still never overwrites it.

`source` describes provenance, not independent human verification or proof of play/viewing. New client-supplied references are stored as manual regardless of supplied metadata. Existing server provenance is preserved by reference ID across edits, including old-client payloads. New recommendations have empty `similarities` and null `reason`.

Optional recommendation failure does not fail base import or clear prior references. All metadata lookups successful (or recognized empty section) → available; some usable names → partial; page/parse failure or no usable names for a nonempty set → unavailable. Missing section is not treated as successful empty. Overall analysis failure retains the existing publication behavior: no partial Profile overwrite.

Steam import increments revision as before. Successful analysis publication increments revision whenever a recommendation fetch was attempted, including unavailable status, so clients can refresh source status and references.

## Minimal opt-in wire contract

New clients send `X-FMG-Steam-References: 1` on authenticated workspace API requests. Do not send this header to external links/images.

With the header:

- ReferenceWork adds `source: "manual" | "steam_more_like_this"` and `source_url: string | null`. Its existing `url` remains the target game's canonical Store URL; source_url identifies the source game's recommendation page.
- GameDetail adds `steam_recommendations: {status: "not_fetched" | "available" | "partial" | "unavailable", source_url: string | null, fetched_at: ISO8601 | null}`.
- Old stored data defaults to manual provenance and not_fetched status.

Without the header, API v2 responses omit these additions, including nested frozen Game/reference objects and idempotency-cache replay. `Vary` includes the feature header. The stored response/schema is unchanged by negotiation; request hashes do not depend on the header. This is one feature projection for installed internal.4 compatibility, not a general versioning framework.

## Verification and release boundary

Targeted tests cover gateway parsing/names/failure, dedup/manual preservation/deletion/retargeting, synchronous import → edit/remove → refresh → analysis, failed optional fetch, old/new import replay, Library detail/list and nested draft DTOs. One bounded independent review found a manual-reference deletion gap; GamePatch dismissal tracking and unit/API regressions fixed it, and remediation was accepted.

Synthetic actual API DTOs are exported by `test_steam_reference_import.py` and `test_steam_reference_compat.py` when `FMG_STEAM_DTO_EXPORT_DIR` is set. No production edits or real email are needed for these checks.

Deployment requires the coordinator's window: normal existing backup/build/restart workflow, no schema upgrade beyond current 0021. Old clients keep working without the feature header; the new desktop package enables provenance/status UI. Do not backfill the user's current LIMINAL record or start a new import/analysis without explicit direction.

## Deployment evidence — 2026-09-10

The coordinator granted the maintenance window after exact internal.5 package and compatibility checks. Backend commit `97f3c19d2694c0a158d461791e4616a153f4a413` was deployed using the existing deployment script; migration remains `20260909_0021`. The prior `684a120` API/Worker/Beat images are retained as `rollback-684a120`, and Git ref `rollback-steam-684a120` retains the previous code. Root-only configuration archive: `/var/backups/find-me-gamer/20260910-steam-references/config.tgz`.

No active work was present before maintenance. All six services recovered healthy. All 42 database tables had identical counts and full-record SHA256 fingerprints before and after deployment, including the user's new Game `c14b93f0-bbae-4709-a327-818f22bc5001`, 22 Creators and four encrypted service configurations.

Pre-maintenance database backup (including the user's new Game and X configuration): `s3://zhangyue-data-493392056671-us-west-2/backups/20260910T044457Z-97f3c19d2694-pre-migration.dump`. The dump and checksum were downloaded to the root-only server backup directory; SHA256 validation passed. No full restore drill was repeated. Subsequent colleague writes must not be overwritten by a blind full restore.

External authenticated HTTPS GET checks passed: readiness/session, existing Game without the header (legacy shape), the same Game with opt-in (not_fetched/null source/null fetched_at), and 22 visible Creators. Existing references remain empty; no automatic source fetch, reanalysis, backfill, new activity, SMTP or AI call was initiated. Real recommendation content verification occurred earlier against Steam without Profile persistence.
