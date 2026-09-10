# Creator Search deployment acceptance — 2026-09-10

## Production release

- Endpoint: `https://44.233.174.193`.
- Exact deployed code: `4178adc3efc99e3b04901b6d0157533c3ea279e5`, including backend `755cc48`, confidence-prompt correction `0180589`, and the integrated desktop source.
- Previous deployed code: `97f3c19d2694c0a158d461791e4616a153f4a413`.
- Alembic: `20260909_0021` → `20260910_0022`; the deployed API reports `20260910_0022 (head)`.
- API, Worker, Beat, PostgreSQL, Redis and Caddy are healthy. HTTPS readiness and authenticated session reads passed.
- The subsequently created internal.6 packaging-only commit `0e94bf2` was not deployed. Desktop artifact publication belongs to the coordinator.

## Maintenance and preservation

Preflight found no active business rows; Celery active, reserved and scheduled inspections were empty. The existing clean server checkout was updated from a verified Git bundle to the exact target. Old images and protected configuration were retained before building.

API, Worker, Beat and proxy were stopped for the authorized maintenance window. PostgreSQL and Redis remained available. Migration ran only after a fresh database backup was uploaded, downloaded and verified. No rolling-worker compatibility assumption was made.

All **41 original non-migration tables** retained identical deterministic full-row SHA256 fingerprints and row counts immediately after migration and again after restarting services and performing read checks. The only changed original table is `alembic_version`. Both new tables, `creator_searches` and `creator_search_units`, are empty.

Preserved records include 1 Game, 68 Creators, 29 contacts, 314 works, 31 analysis jobs, 1 Activity, 1 discovery plan/query/batch, 68 discovery candidates, 68 activity selections and all 4 encrypted service-configuration rows. Existing empty evaluation and delivery histories remain empty. `app.env` and `master.key` checksums are unchanged and permissions remain root-owned 0600.

The old 68-candidate activity was **not** submitted to Creator Search or evaluation. No production task, Profile, contact or email was created by acceptance checks.

## Backup and rollback boundary

- Bucket: `zhangyue-data-493392056671-us-west-2`.
- Verified pre-migration object: `backups/20260910T060104Z-4178adc3efc9-pre-migration.dump`, plus its `.sha256` companion.
- S3 round-trip download and SHA256 verification passed. PostgreSQL `pg_restore --list` successfully read the custom-format dump.
- This round **did not** execute a complete isolated database restore drill or perform a rollback.
- Server evidence directory: `/var/backups/find-me-gamer/20260910-creator-search-4178adc` (0700). It retains the downloaded dump/checksum, dump table-of-contents, before/after fingerprints and root-only `config.tgz` (0600).
- Previous Git state: `rollback-creator-search-97f3c19`.
- Previous application images: `find-me-gamer-api:rollback-97f3c19-creator-search`, `find-me-gamer-worker:rollback-97f3c19-creator-search`, `find-me-gamer-beat:rollback-97f3c19-creator-search`.

Rollback artifacts are available, not proof of a tested rollback. Restoring the pre-migration dump after colleagues resume work would overwrite later writes; it requires a separate maintenance decision and a fresh backup. Do not casually restore or downgrade a live database.

## Production read-only acceptance

Successful authenticated HTTPS checks covered readiness/session, reanalysis and collection settings, SMTP configuration status, Activity list/detail, the existing discovery query and all 68 candidates, empty evaluation history, Library lists, Game detail with and without the Steam-reference opt-in header, and all 68 Creator details.

New route checks covered the existing Activity's empty Creator Search history with `limit=100`, and expected 404 responses for nonexistent Search detail and Search Creator-list IDs. Worker inspection confirms registration of `find_me_gamer.creator_search.run`. Registration is not presented as production execution of that task.

Actual production response bodies were decoded with **frozen internal.5 code from `02e0989`**: Activity list/detail, query, all 68 candidates, empty evaluations, legacy/opt-in Game detail and all 68 Creator details passed. The internal.6 decoder accepted the new empty Search history. This verifies wire compatibility; it is not a manual end-to-end interaction in an installed internal.5 app.

Ignored local evidence: `.local/cloud-deploy/creator-search-production-dto.json`, `.local/cloud-deploy/creator-search-production-read-cache.json`, and `.local/cloud-deploy/creator-search-compat/`. Credentials were not printed or added to Git.

## Separate pre-deployment model and worker evidence

These checks were isolated/local and must not be confused with a full production external-service test:

- Initial backend feature regression: 53 passed. Confidence-fix regression selection: 53 passed. These are overlapping selections, not 106 unique tests.
- Real Redis/Celery worker tests: 3 passed, including native API dispatch, duplicate delivery, partial retry and stop/resume behavior. External providers and models were synthetic in those tests.
- Bounded independent reviews accepted the feature and the confidence correction without remaining blocking findings.
- A single existing YouTube Creator/Game snapshot was evaluated in an isolated database using real DeepSeek. The original 3 requests exposed an evidence-confidence prompt mismatch. The fix explicitly instructs the model that thematic fit does not establish verified evidence; validators were not weakened.
- Exactly 2 additionally authorized requests retried only Deep Match and then ranking. The result was `completed`, 1 matched Creator, with screening/Deep Match/ranking succeeded. Corrected Deep Match returned `limited`, consistent with the source evidence.
- Total actual model HTTP requests: **5**, consuming **21,421 tokens**. The final two consumed 6,282 + 1,388 = 7,670 tokens. No sixth request was sent.
- That isolated check made zero acquisition, Gemini or SMTP calls and zero production writes. The local encrypted DeepSeek key was used in memory, not persisted to the probe database.
- Retained report: `.local/creator-search-real-model/report.json`; original failure baseline: `report-original-3.json`; isolated database: `creator_search_model_4165408a4d4743b78496776cdd7eca11`. Preserve until overall acceptance authorizes cleanup.

## Operational notes and remaining limits

The first remote script transport used `bash -s`; a child process consumed remaining standard input after backup, so it ended before migration. Services remained stopped and the database was unchanged. A separately uploaded, state-checked resume script produced a fresh verified backup and completed migration. Future deployments should execute an uploaded script file, not stream a multi-step script alongside stdin-consuming commands.

The first Game comparison in the acceptance script omitted the already-defined `source`/`source_url` projection on reference works. The checker was corrected against the existing contract; no application code changed. Bulk HTTPS checks encountered local TLS EOFs, then the existing 60-requests/minute workspace limit during a faster retry. Using the existing local proxy and serial checks capped below 40/minute completed successfully. No network, IAM or rate-limit settings were changed.

SMTP remains unconfigured. Real mailbox enhancement/Gemini, live X discovery and the complete acquisition → analysis → email enrichment → matching chain were **not** collectively re-executed against production in this maintenance window. Do not describe the release as a freshly validated full external-service E2E run. No real email was sent. Existing Twitch/Instagram scope is unchanged.

The EC2 operations skill guided the maintenance and rollback-artifact checks. Existing instance/role/storage were reused; no new infrastructure or IAM permissions were introduced. This deployment closes the bounded internal-Demo release task, without expanding to rolling upgrades or unrelated defensive hardening.
