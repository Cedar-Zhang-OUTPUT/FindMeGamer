# Native Match: bounded screening and retry checkpoints

## Scope and deployment

Backend implementation: `944287c70259f51e285539ed48c9001945b53fe2`, pushed to `codex/native-profile-editing`.
Deployed on 2026-09-14 at 15:30 UTC to the existing US EC2 Compose stack.
Application image: `find-me-gamer-native:0.4.1-944287c`.
Source directory: `/opt/find-me-gamer-native-041-screening`.
Migration head: `20260914_native_0013`.

This is a backend-only update compatible with the published native 0.4.1 client. No new DMG, frontend changes, additional services, data reset, analysis retry, or email sending was needed.

## Behavior

Previously, all eligible Library briefs were included in one screening request, even when split into multiple messages. A realistic 1,200-creator fixture exceeded the complete-request guard.

- Screening now sends independent calls with at most 100 creators each and a 400,000-byte message-content budget. Large groups are split further; records are not truncated or silently omitted. This is a conservative byte bound, not an exact tokenizer count.
- All leaf batches are processed before bounded reductions over their screening summaries. At most 30 candidates enter the existing detailed pairwise matching and ranking flow. Selection limits are ceilings, not promised result counts.
- Validated initial and reduction responses are checkpointed by request hash in short transactions. Existing task retries reuse successful calls for the same frozen inputs, model and prompt rather than replaying them.
- A task-scoped PostgreSQL advisory lock prevents duplicate screening deliveries from making concurrent model calls. Expired terminal task checkpoints follow the existing retention lifecycle.
- DeepSeek analysis, screening, pairwise and ranking model constants remain `deepseek-flash`. Gemini email research is unchanged.

## Verification

- New large-library tests first reproduced the original failures. A duplicate-delivery regression also failed before the advisory-lock fix.
- Final full backend regression: **1,996 passed, 3 existing skips**, 160.38 seconds; one existing Starlette deprecation warning.
- Isolated real API/PostgreSQL/executor-graph test with 1,200 synthetic creators: fail the second screening call, retain the first checkpoint, retry via the existing API, process every input without replaying the first call, then complete pairwise and ranking. Reduction retry, populated migration, checkpoint expiry and duplicate execution are covered.
- Independent scoped review approved the implementation without release-blocking findings.
- A small real-provider smoke used six existing briefs with the new image and production Flash gateway: screening selected six; reduction selected three. Output schemas and candidate IDs validated. This read-only database check made two paid model calls, created no task and retried no historical work. **A 1,200-person paid production run was not performed.**
- After deployment, API, Worker and Beat all reported healthy on the new image. Public readiness returned `ok`; unauthenticated Discover returned 401; authenticated session, Game Library, Creator Library and Discover reads succeeded. Existing 100-candidate Discover history remained readable.

## Data protection and rollback

Deployment checked for queued/running analysis, discovery, discovery-analysis batches and Match tasks before entering maintenance, stopped API/Beat, rechecked, then stopped Worker. The migration adds only the checkpoint table.

Fresh backup:

- Server: `/var/backups/find-me-gamer/native-screening-20260914/native.dump`
- S3: `s3://zhangyue-data-493392056671-us-west-2/backups/native-screening-20260914/native.dump`
- Size: 1,510,563 bytes
- SHA-256: `1c7809a749d7d218a6ccb2dcefb0ba85cafa86cb43053ca0019a6e26c8f37179`

The dump was checked with `pg_restore --list`; uploaded dump and checksum were downloaded and byte-compared. Before/after whole-table row digests matched for every existing table except the intended Alembic revision change. The new checkpoint table was empty. Post-deployment counts: one Game, 35 Creators, 65 analysis jobs, three Discover jobs, zero Match tasks. These were preserved, not reset. Caddy was not restarted and the 0.4.1 update feed was unchanged.

Previous application source and runtime override remain at `/opt/find-me-gamer-native-040-platform20`, image `find-me-gamer-native:0.4.0-cec8ea9`. A rollback can restore those application images with a maintenance window; the additive checkpoint table does not require deleting or restoring the database.

Local verification logs: `/tmp/fmg-match-batches-full.log`, `/tmp/fmg-screening-live-smoke.log`, `/tmp/fmg-screening-deploy.log`, `/tmp/fmg-screening-runtime-verify.log`, `/tmp/fmg-screening-public-smoke.log`.
