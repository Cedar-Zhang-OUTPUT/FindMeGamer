# FMG CLI / Skills 0.7.4 — lightweight outreach status

- `fmg outreach task get TASK_ID --summary` requests `GET /v1/outreach/tasks/{id}?summary=true`: task identity, revision, state, all delivery/retry/reply statistics, sender safety and monitor health, without recipient drafts, template or reply bodies. Summary SQL defers frozen image-bearing message payloads and reads only reply identity/kind. Ownership and email-send scope checks are unchanged.
- Existing full queries, dashboard review and immutable previews remain compatible. HTTP gzip compression reduces repeated draft/reply transfers for old CLIs too. Stored payloads, actual email MIME and approval scope are unchanged.
- CLI distinguishes `request_timeout`, `response_incomplete` and `response_too_large`. No automatic request retries; uncertain mail must be queried, not resent. Both Skills' outreach references route progress/pre-batch checks to summaries and keep full draft review and explicit approval.
- API-only deployment: no worker restart, database migration, sender release, task approval or production test email. Versioned prior image and deployment snapshots retained for rollback.

Upgrade: `fmg upgrade --latest --skills`, verify `fmg version`, then re-read both installed Skills and outreach references. Preserve existing task IDs/revisions and approved send scope.

## Local verification

- Backend full suite: 282 passed, one opt-in Docker smoke skipped because local Docker remains stopped. Real isolated PostgreSQL, Redis, compiled CLI, local SMTP/worker restart and dashboard tests included. Existing Starlette/AnyIO deprecation warning remains.
- Go full tests and vet passed; four-platform release archives built. Installer/bundle tests: four passed. Both Skill validators passed.
- New tests cover summary size/SQL projection, owner/scope boundaries, pending/accepted/retry/uncertain/human-reply/sender-hold state, PostgreSQL JSON projection, gzip legacy compatibility, actual CLI/HTTP summary use, timeout-before-headers, timeout-during-body, interrupted body and oversized response classification. No tests send external email.

## Production verification — 2026-10-12

- API image `fmg-agent:query-2033d4a` is healthy. The worker container was not restarted. Before/after snapshots confirm unchanged send counts, task revisions, frozen draft digests, sender safety, retry queues and database migration version. Mail monitoring remains active.
- Actual HTTPS checks using CLI 0.7.4: three summary queries each for batches 15 and 16 passed, 708–716 bytes, 0.59–1.71 seconds on this machine's direct connection. The summaries agree with CLI 0.7.3 full-query statistics/revisions; both legacy full queries passed (1.16 and 5.73 seconds).
- One additional summary query through this machine's configured proxy timed out; two preceding proxied queries passed. Direct verification above passed all eight requests. Compression and summaries address the response-size bottleneck, not independent network/proxy outages; the CLI now reports timeouts distinctly.
- Batch 16 remains awaiting approval with 50 pending recipients and no send attempts. No task was started, mailbox hold released or production email sent during deployment/verification.
- Prior image and private deployment snapshots remain available for rollback at `/var/backups/find-me-gamer-agent/query-2033d4a-20261012`.
- Public release acceptance: anonymous downloads from the server verified SHA256SUMS for all four CLI archives, the Skill bundle and installer. An isolated CLI 0.7.3 installation successfully ran `fmg upgrade --latest --skills` to 0.7.4 and installed both 0.7.4 Skills; that downloaded binary queried batch 16 successfully without sending. `fmg update check --refresh` on a working connection resolves 0.7.4 and reports both Skills current. This machine's proxy made downloads slow and one update check unavailable; direct GitHub asset access also timed out, independently of the API fix.
