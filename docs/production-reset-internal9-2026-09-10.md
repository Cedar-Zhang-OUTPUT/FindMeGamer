# Production business-data reset after internal.9

Completed on **2026-09-10**, following explicit authorization to remove all
production Game/Creator Profiles and business history while preserving service
configuration, authentication and backups. The coordinator confirmed internal.9
was published and its uploaded DMG digest matched before execution was released.

## Verified target and retained configuration

- EC2 `i-041e77ab08c86ff1d`, account `493392056671`, `us-west-2a`, public IP
  `44.233.174.193`. Identity was checked using IMDSv2; S3 used the instance role.
- Application checkout `/opt/find-me-gamer`, unchanged deployed revision
  `991a8efbc21a1203fe1ec4c131bdac6dc7bba862`. No diagnostic/code deployment was
  mixed into this reset.
- PostgreSQL database `find_me_gamer`, Compose service `postgres`, schema revision
  `20260910_0022`. No schema migration or volume deletion.
- All rows in `shared_settings` (1), `service_secrets` (4), and `alembic_version`
  (1) were preserved with identical before/after content hashes. Configured
  provider names remain DeepSeek, Google AI, X and YouTube; no SMTP secret was
  added or removed.
- `/etc/find-me-gamer/app.env` and `master.key` retained identical SHA256 values,
  root ownership and mode 0600. Caddy certificates/configuration, deployment
  records, existing backups and S3 `deployment-probe.json` were not deleted.

## What was removed

At final database verification, **19:18:53 Shanghai**, the exact 41-table business
allowlist contained **0 rows**, down from **3,545** at the stopped-service baseline.
This includes 68 Creator Profiles, 1 Game Profile, 86 analysis jobs, 960 analysis
checkpoints, 58 contacts, 1,738 works, 2 Activities, 118 discovered candidates and
118 selections, all discovery/evaluation history, 100 frozen recipients, 100 drafts,
and all legacy/new matching, outreach, response and collaboration records.
Business idempotency records and the analysis change watermark were also reset.

The tables were truncated together in one transaction with **RESTRICT**, without
CASCADE, after checking the complete public-table set. No unknown table or
protected configuration table was included.

S3 live `acquisition/` contained 188 objects: **187 identified business JSON
artifacts were removed**, and the single deployment probe was retained. Deletion
used an explicit validated manifest; it did not delete the bucket, modify bucket
policy, or touch the `backups/` prefix.

The two known isolated-model-probe directories were archived and removed from
the active API container after upload/readback verification:

```
/tmp/fmg-deep-failure-20260910-v1
/tmp/fmg-deep-failure-20260910-v2
```

No other `/tmp` directory or unrecognized resource was deleted. Anonymous source
code, validation reports and diagnostic documents remain available.

## Backup and recovery evidence

Full custom-format PostgreSQL backup and checksum:

```
s3://zhangyue-data-493392056671-us-west-2/backups/20260910T111757Z-991a8efbc21a-pre-migration.dump
```

The dump was downloaded from S3 and checksum-verified, then restored with
`pg_restore --exit-on-error` into the isolated database
`fmg_reset_verify_20260910`. **All 44 tables' row counts and content hashes matched
the stopped-production baseline.** That temporary verification database was
removed afterward. This was a real restore, not merely a TOC check.

Cache recovery copies:

```
s3://zhangyue-data-493392056671-us-west-2/backups/20260910-internal9-reset/acquisition/
```

All 187 copied keys, sizes and ETags matched the source manifest before deletion.
The two diagnostic tar archives and SHA256 sidecars are under the same reset
prefix's `diagnostics/` directory; each archive was downloaded and byte-compared
before its source directory was removed.

Root-only local evidence, dump, configuration archive and manifests:

```
/var/backups/find-me-gamer/20260910-internal9-reset
```

Backups use the existing `backups/` prefix, documented in the infrastructure
handoff as having a 30-day lifecycle. The instance role could not independently
read lifecycle/versioning configuration (`AccessDenied`), so this run did not
claim to reverify that policy or rely on S3 object-version recovery. Recovery
relies on the explicitly verified copies above. Existing backups were preserved.

### Recovery procedure (requires separate authorization)

Restoring old history would replace or merge with subsequent fresh testing data;
do not run it automatically.

1. Close ingress and stop API/Beat, verify no active/reserved/scheduled work or
   pending/unacknowledged broker messages, then stop Worker. Preserve a new backup
   of any data created since this reset and the current configuration hashes.
2. Download the named dump and `.sha256`, verify the checksum, and first restore
   to a fresh isolated database. Compare against `db-before.json` from the evidence
   directory before promoting/restoring the approved database contents.
3. Keep current authentication/service settings protected unless a configuration
   rollback was also explicitly requested. The reset-time dump includes their
   encrypted rows; the retained matching master key is necessary to decrypt them.
4. If required, copy the cache recovery objects back to their exact original
   `acquisition/` keys using `cache-manifest.json`. Do not delete backup objects or
   infer versioning support. Verify key/size/content metadata after restoration.
5. Restore healthy services and verify the selected recovery state through the
   API. Diagnostic archives are evidence, not something to replay as model calls.

## Maintenance safeguards and final acceptance

One bounded independent execution review required an additional broker check
after Worker stopped; that check was added before the destructive phase. API,
proxy and Beat were closed before Worker was stopped. No queue was purged and no
Redis database/volume was flushed.

Two pre-deletion tool checks stopped safely: a normal short-lived authentication
rate-limit key was conservatively rejected as non-binding Redis data (it expired
naturally), and the one-off audit container needed `PYTHONPATH=/app` when executing
its mounted script. Both happened **before backup/destructive work**; bounded
resume guards ensured the verified phase was continued without rerunning deletion.
No data or credentials were modified to bypass those checks.

Final verification:

- API, Worker, Beat, proxy, PostgreSQL and Redis all healthy.
- Public HTTPS `/health/ready` returned `{"status":"ok"}`.
- Worker active/reserved/scheduled counts were all zero; no pending or unacked
  broker messages remained. Binding metadata was retained.
- All 41 business tables were empty; all three protected table hashes matched.
- Authenticated HTTPS Game Library, Creator Library and Activity list requests
  returned 200 with `total=0` and empty items. The old Search detail returned 404.
- S3 had zero live business acquisition artifacts and one preserved deployment
  probe. No model/provider acquisition or SMTP request was initiated.

Clients should refresh or reopen before creating new Activities so their local
view no longer refers to deleted historical IDs. The new run starts from an empty
business Library without requiring service keys to be entered again.
