# Production business-data reset — internal.11, September 13

Completed a **new explicitly authorized reset** on 2026-09-13, after the user asked
to clear all Games, Creators and analysis history before starting fresh. This did
not replay the September 10 operation or reset the local desktop test fixture.

## Verified target and scope

- Production `44.233.174.193`, application `/opt/find-me-gamer`.
- Deployed backend remained `14d0a6ca60f8fbe03647136a61e64c0cf1cd76ff`.
- PostgreSQL database `find_me_gamer`; migration remained `20260913_0023`.
- Schema was exactly the existing 44-table set: 41 business tables and 3 protected
  tables. 0023 adds a draft column, not a new table. Foreign-key dependencies were
  inspected before reusing the existing exact reset allowlist.
- No instance, database volume, Redis volume, S3 bucket, certificate, service
  configuration, credential or existing backup was removed or reconfigured.

## Deleted business data

The stopped-service baseline contained **2,632 business rows**; all 41 authorized
business tables were empty after the single `TRUNCATE ... RESTRICT` transaction.
No `CASCADE`, broad database drop or Redis flush was used.

The deleted scope included:

- 1 Game and 38 Creator Profiles, 1,602 works and 43 Creator contacts.
- 55 cumulative Analysis Jobs and 594 analysis checkpoints.
- 1 Activity, discovery/search/evaluation records, 38 selections, 46 frozen
  recipients, 5 compositions and 54 drafts, including the saved draft.
- Associated legacy/new Match, outreach, template, response, collaboration and
  saved-list tables, plus business idempotency records and the analysis watermark.
  Several of these tables were already empty.

The 55 Analysis Jobs were 33 succeeded + 22 failed **historical tasks**, not
55 distinct Creator Profiles. No active or unknown-outcome business task or
email delivery was found at the final pre-deletion checks.

S3 `acquisition/` had **114 business JSON artifacts** and one deployment probe.
Each deleted key matched an approved raw-artifact filename and an Analysis Job ID
in the actual preflight database. All 114 business objects were copied and verified
before exact manifest deletion. The deployment probe and all `backups/` objects
were preserved. No unrelated directory or object prefix was deleted.

## Preserved configuration

These tables retained identical before/after row counts and full-content hashes:

- `shared_settings`: 1 row.
- `service_secrets`: 4 rows.
- `alembic_version`: 1 row, version 0023.

Existing DeepSeek, Google AI, X and YouTube service credentials remained configured.
Existing SMTP/API settings, workspace authentication and other shared settings were
not changed. No SMTP credential was newly added. `/etc/find-me-gamer/app.env` and
`master.key` retained matching SHA256 values; certificates and infrastructure were
untouched. Credentials and original profile contents are not included in this report.

Redis checks confirmed no pending or unacknowledged messages. Four broker binding
keys and two normal expiring authentication rate-limit counters were retained.
**Zero Redis keys were deleted.** Short-lived auth counters are not profile caches.

## New backup and recovery evidence

This operation created a new database backup, separate from the earlier deployment
backup:

```text
s3://zhangyue-data-493392056671-us-west-2/backups/20260913T082538Z-14d0a6ca60f8-pre-migration.dump
```

Its name uses the existing backup script's `pre-migration` marker; this reset did
not run a migration. The dump contains the stopped-production 0023 database,
including the protected encrypted configuration rows.

The dump and `.sha256` were downloaded back from S3. Checksum validation and
`pg_restore --list` succeeded. **This run did not perform a complete restore or
claim a restored-database fingerprint comparison.**

Verified raw-artifact recovery copies:

```text
s3://zhangyue-data-493392056671-us-west-2/backups/20260913-internal11-reset/acquisition/
```

All 114 backup keys, sizes and ETags matched the frozen acquisition manifest before
deletion. After deletion, only the single deployment probe remained in the live
acquisition prefix.

Root-only evidence directory:

```text
/var/backups/find-me-gamer/20260913-internal11-reset
```

It contains the exact scripts, preflight/quiesced inventories, stopped database
baseline and empty post-reset counts/hashes, backup URI/dump/checksum/TOC,
configuration archive/checksums, acquisition and deletion manifests, broker guards
and final verification. Existing backup retention was not changed or reverified;
do not assume these recovery copies are permanent.

Recovery requires a separate explicit request: first protect any newly created
data, stop writers, download and checksum-verify this backup, and restore into an
isolated database for inspection. A production restore must account for later
data/configuration changes; do not overwrite them automatically. The retained
matching master key is necessary for encrypted secrets. If raw artifacts are
needed, copy the verified backup objects to the exact original manifest keys.

## Execution safeguards and final acceptance

The existing validated reset flow was adapted only for the current date, commit,
0023 schema and exact 114-object manifest. One bounded independent read-only
review found no blockers and explicitly identified the backup verification boundary
above; no new reset framework was developed.

Worker active/reserved/scheduled and business active/unknown status were checked
before maintenance and after API/proxy/Beat stopped. The idle Worker was then
stopped; the broker was checked again afterward and immediately before clearing.
New database and artifact backups were verified before deletion. No paid provider
call, reanalysis, retry, SMTP send or automatic restoration was initiated.

Final results:

- API, Worker, Beat, proxy, PostgreSQL and Redis healthy.
- Public HTTPS readiness: `{"status":"ok"}`.
- Real authenticated HTTPS Game Library, Creator Library and Activity list requests:
  **200**, `total=0`, `items=[]` for all three.
- The former Creator Search detail returned **404**.
- All 41 business tables empty; all three protected tables unchanged.
- No active/reserved/scheduled Worker work, pending/unacknowledged broker messages
  or live business acquisition artifacts remained at verification.

Colleagues can **refresh or reopen the client and start a new analysis**. Existing
service keys do not need to be entered again. Old local selections may reference
deleted IDs until refreshed; do not retry old Activity or draft mutations.
