# Recovery deployment — 2026-09-10

Deployed fixed backend revision **991a8efbc21a1203fe1ec4c131bdac6dc7bba862**
to `44.233.174.193`, including e924c52 (DeepSeek model names), e43b6ed
(ordinary narrative validation), and 991a8ef (failed-node recovery).
Previous deployed revision: `4178adc3efc99e3b04901b6d0157533c3ea279e5`.

## Maintenance and preservation evidence

- At 17:16 Shanghai the specified 50-person Search remained naturally terminal;
  database work and worker active/reserved/scheduled were empty. Checks repeated
  after building, and again after closing proxy/API/Beat before stopping Worker.
- Used uploaded scripts executed by pathname, not `bash -s`; nested Docker and
  backup commands receive explicit input so they cannot consume deployment code.
- Fixed-SHA bundle and scripts matched local/remote SHA256 before execution.
- All **44 public tables** (43 business tables plus Alembic) retained identical
  row counts and content fingerprints across maintenance/migration. Alembic
  remains **20260910_0022**; no migration or historical-data rewrite was added.
- `/etc/find-me-gamer/app.env` and `master.key` remained root-owned mode 0600;
  before/after SHA256 matched. No service key, SMTP setting or environment change.
- API, Worker, Beat, proxy, PostgreSQL and Redis all healthy; public HTTPS
  `/health/ready` returned `{"status":"ok"}`.

## Backup and rollback

Instance-role S3 access was used; no embedded AWS credentials or IAM changes.
Backup uploaded with server-side encryption, downloaded, checked against its
SHA256 sidecar, and read with `pg_restore --list`:

```
s3://zhangyue-data-493392056671-us-west-2/backups/20260910T091940Z-991a8efbc21a-pre-migration.dump
```

This is checksum/archive-structure verification, not a full restore drill.
Root-only evidence/config archive/downloaded dump:

```
/var/backups/find-me-gamer/20260910-recovery-991a8ef
```

Old application images retained as
`find-me-gamer-{api,worker,beat}:rollback-4178adc-recovery`; server Git rollback
branch `rollback-recovery-4178adc` points to the prior revision. Configuration
archive and checksums are in the evidence directory. Database restore is not
needed for a code-only rollback of this unchanged-schema deployment.

## Read-only post-deployment acceptance

Actual authenticated HTTPS GETs, with response bodies kept private, covered:
Search detail and 50 people, Activity detail, Query, Evaluation and 30 results,
Game legacy plus Steam-reference opt-in projection, and three Creator details
representing newly ready/reused/failed states. Current and frozen internal.5
Game/Creator/Activity/Query/Evaluation decoders passed; current Search decoders
passed. No claim of a new GUI or paid end-to-end run is made.

After these GETs, a second all-table fingerprint comparison against the maintenance
baseline remained byte-for-byte equal (`post-read.json`). Runtime imports verified
all Creator model stages select `deepseek-flash`, the 32KB/8KB guards are present,
and the failed-node recovery functions are installed. Configuration hashes and
empty worker queues were checked again without changing state.

17:20:57 Shanghai snapshot: same Search `partial/complete`, 30 usable Profiles,
20 failed Profiles, 18 available emails and 12 missing. Evaluation still has
16 successful deep steps, 9 failed deep steps, 2 successful screening steps and
1 successful ranking step. Worker `celery@e3fae9abf257` reported empty active,
reserved and scheduled queues. No analysis/discovery/evaluation task was started.

## Explicit next release gate

**No retry dispatched and no model/provider probe or SMTP send performed.**
The coordinator must separately release one idempotent retry of Search
`01b3b649-f5ad-40b1-a146-aac2d666e1ea`. It covers 20 failed YouTube Profile units
(all previously validated as checkpoint-recoverable) and 9 failed evaluation
steps. Successful Profile/analysis/evaluation outputs remain reused; new results
may require additional screening/deep/ranking. No full rediscovery, append,
old 68-person Activity, or unbounded retry loop is authorized.
