# Planning maintenance deployment — 2026-09-09

## Final version and verification

- Origin: `https://44.233.174.193`; existing EC2/Compose installation.
- Final application commit: `17aad383e1965b639eb88151493e44cc7165b2b7`.
- Earlier keyword/logging patch: `1296f279f2a00706619a0e4c9b40717c2ebc5a0d`.
- Previous release: `5706ad76f924991b80ee2a7fb6806528366be5ce`.
- Migration remains `20260908_0019`; no new migration or database reset.
- Final focused gate: **154 passed**, one existing Starlette/AnyIO warning.
- Original bounded review accepted; the subsequently observed platform-mismatch
  blocker received only a targeted incremental review, also accepted.
- All six containers are running and healthy; server checkout is clean and final
  Redis queue depth is zero. HTTPS readiness, authenticated session/settings,
  Activities, original failed-plan readback, both Library lists and all23 Profile
  details returned200. Config archive comparison matched the current files.

See `planning-failure-fix-2026-09-09.md` for the diagnostic sequence and TDD.
The exact cause of the original historical failure remains unproven. A fresh
real call after1296f27 specifically exposed `planning_platform_invalid`;17aad38
places that request-specific validation within the existing single repair.
It does not create an additional retry loop or weaken the output contract.

## Real model and platform acceptance

All live diagnostic calls used the original failed plan's frozen Game/conditions
in independent Python processes. Original records were read-only; no replacement
Activity, discovery query, candidate or email was created.

- 1296f27 isolated pre-deploy patch: one DeepSeek call; YouTube two requests,
  10 accounts/10 contents, `more`, no issues.
- 1296f27 deployed verification: `planning_platform_invalid`; this was not hidden
  by repeated attempts and triggered the narrow follow-up fix.
- 17aad38 isolated pre-deploy patch: one DeepSeek call; YouTube two requests,
  nine accounts/10 contents, `more`, no issues.
- 17aad38 **deployed code, no in-process patch**: one DeepSeek call, valid three-term
  YouTube-only plan; compiled YouTube search completed normally with **zero results**
  and no issues. It used one search request, no channel enrichment needed.

The last result establishes successful planning and provider execution, not a
guarantee of nonempty retrieval or relevance. Do not report it as finding creators.
No repeated sampling to obtain a favorable count or search-recall redesign was done.
Persistent invalid model output still fails visibly after the bounded repair and
requires explicit user Retry. The original failed plan remains failed/attempt1,
query null; it was not automatically replayed as a persisted worker task.

## Data/config preservation and rollback

Before and after both deployments, canonical full-row SHA256 fingerprints matched
for all16 checked tables: Game1, Creator22, contacts29, works264, analysis jobs32,
legacy Match3, encrypted service secrets3, Activity1, failed discovery plan1;
discovery queries/batches/candidates and both legacy/v2 deliveries/send batches0.
Analysis statuses remain25 succeeded/seven failed; legacy Match tasks all succeeded.
Original plan `83d03259-473f-4847-8028-1d4c31df007c` and frozen Game are unchanged.

Maintenance stopped Proxy/API/Worker/Beat; Redis queue depth was zero. Protected
configuration was not replaced. Root-only0600 backup archive:
`/var/backups/find-me-gamer/20260909-planning/config.tgz` contains `app.env` and the
master key. Never publish it. Configuration files remain root-owned0600.

S3 bucket `zhangyue-data-493392056671-us-west-2`, existing30-day backup lifecycle:

- `backups/20260909T073236Z-1296f279f2a0-pre-migration.dump` and `.sha256`;
- `backups/20260909T073534Z-17aad383e196-pre-migration.dump` and `.sha256`.

Both were generated with writers stopped, uploaded with AES256, downloaded again,
SHA256 checked, and parsed by `pg_restore --list` (298 lines each). Protected local
copies are next to the config archive. These exact dumps were **not** subjected to
another full restore rehearsal; the earlier release's restore rehearsal is recorded
in `cloud-handoff-2026-09-09.md`.

Rollback images `find-me-gamer-{api,worker,beat}:rollback-5706ad7` and server Git ref
`rollback-planning-5706ad7` preserve the original release. Schema has not changed;
rollback, if necessary, must stop writers and preserve any intervening data first.
No rollback or database restore was executed.

Code-only incremental Git bundles were SHA256-verified and imported into the
existing local bare mirror without force-pushing main:

- 1296f27: `449ed75c1a88cb9f77a2154da4123d9015247dfd301796e10a6b374ba7701d83`
- 17aad38: `7ecd4f653169276b5afcd07cbd370e79883ed247a46a61b0c480d5486a17587b`

No IAM/network changes, new infrastructure, frontend edits, SMTP sends or
Twitch/Instagram calls were made. Internal.3 packaging/release remains with the
coordinator. Existing independent frontend fixtures were not touched.
