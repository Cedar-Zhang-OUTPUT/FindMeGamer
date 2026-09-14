# Provisional Instagram import: 100 records

The user approved provisional `ig-<lowercase username>` keys for manual Instagram collection, instead of requiring an unavailable official numeric account ID. This is a bounded extension to the existing import tool, not a platform API integration or automatic identity-rebinding system.

## Implementation and validation

Code: `1180f50` on `codex/native-profile-editing`.

- Keys must match the validated Instagram username; Twitch and unrelated keys remain rejected. Provisional records cannot claim an official ID source URL.
- The existing Profile UUID remains the system identity. Source status explicitly marks the provisional key with actual platform ID null.
- Instagram username matching supplements ID deduplication. Existing records under another ID are skipped or refused, never implicitly overwritten/rebound.
- No analysis, Brief, works, email or verified source facts are invented.
- TDD: four positive cases failed before implementation. Targeted suite: 32 passed. Full backend suite: **2,003 passed, 3 existing skips**, 165.98 seconds; one pre-existing Starlette warning. Independent scoped review approved without blockers.
- The 100 normalized records passed a real test-database transaction rehearsal, detail serialization and duplicate-skip check; the rehearsal rolled back.

## Production operation

The updated importer ran as a one-off container image `find-me-gamer-import:1180f50`, sourced from `/opt/find-me-gamer-import-ig-1180f50`, against the existing native database and shared key configuration. No schema migration, API/Worker/Beat restart or client release was required. Their container IDs and start times compared equal before/after. The running API/Worker application image remains the prior `0.4.1-944287c`; this operation deploys the import tool, not a new service release.

Production transaction inserted exactly 100 Instagram records using `on_conflict=skip`. Existing Twitch 100, YouTube 20 and X 15 were preserved; final total 235. No analysis/discovery/Match jobs or emails were submitted. These new records remain fact-only and are not Match-ready.

Before import, a fresh database dump was created, listed with `pg_restore`, uploaded to S3 and byte-compared after download:

- Server: `/var/backups/find-me-gamer/curated-ig100-20260914/native.dump`
- S3: `s3://zhangyue-data-493392056671-us-west-2/backups/curated-ig100-20260914/native.dump`

Material SHA-256: `13ccadbc9ef211691da6883486582b4b9146e0e213c1fe7b44398ab7d8d7952d`. The original colleague files are unchanged. Normalized material and the full original audit are under `/Users/cedar/FeishuFiles/FindMeGamer-import-2026-09-14/`, not committed to the public repository.

Local operation logs: `/tmp/fmg-ig-{full,rehearsal,production-import,public-verify}.log`. Structured source-status identity marking does not claim that the current client has a dedicated provisional-ID badge.
