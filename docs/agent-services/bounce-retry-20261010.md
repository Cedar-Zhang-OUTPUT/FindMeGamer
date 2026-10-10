# One-shot spam-bounce retry — 2026-10-10

Approved behavior: after detecting a first explicit spam-blocking DSN, wait at
least 30 seconds, then resend the exact immutable snapshot once. Three distinct
recipients whose retries explicitly fail within 15 minutes pause the sender.
Graph throttling still pauses immediately. Invalid-address initial DSNs are not
retried; uncertain transport outcomes are not repeated. Existing holds and
blocked tasks are not released/resumed by deployment.

See [bounce-safety.md](bounce-safety.md) for query fields and precise timing.

## Verification

- TDD covered the absent retry behavior first, then immutable one-shot delivery,
  no early reservation, duplicate DSNs, cross-token holds, second DSN/transport
  failures, unknown outcomes, Graph 429, human replies, revoked tokens, historical
  cutoff, blocked batches, cooldown, and interruption recovery.
- PostgreSQL concurrency checks cover concurrent DSN ingestion and concurrent
  retry workers. The full migration/auth/idempotency test exposed a lock-order
  inversion between duplicate reservations and receipt finalization; both now
  acquire sender safety before send/retry rows, with a post-lock replay check.
- SQLite migration with an existing hold first failed, then passed after making
  the cutoff-column migration additive and batch-compatible. Existing hold
  reason/time remain unchanged, and no historical retries are created.
- Full isolated PostgreSQL 17 (UTF-8), loopback Redis, published CLI 0.7.3 and real
  restarted Celery/local SMTP verification: **272 passed, 1 skipped**. The skipped
  opt-in container smoke test remains skipped because local Docker is stopped.
  One existing Starlette/AnyIO deprecation warning remains.
- A preliminary isolated cluster was SQL_ASCII, which made the test driver's
  PostgreSQL version value bytes. It was stopped and replaced by a fresh UTF-8
  cluster; no production code/dependency workaround was added.
- The real worker test receives a fixture DSN, restarts, waits at least 30 seconds
  and delivers exactly one retry to loopback SMTP. No external mail is sent.
- Production pacing is unchanged. The full outcome-focused fixture run sets
  `FMG_AGENT_EMAIL_SEND_INTERVAL_SECONDS=0` only in its process environment;
  dedicated pacing tests explicitly use five seconds and test the shared gate.

## Deployment and rollback boundary

Build a pinned image from the tested commit. Require no in-flight sends, approved
pending recipients, or running enrichment work. Stop API/worker, capture a private
DB dump and runtime/environment backup, then run migration `0011_bounce_retry`.
Validate API health, unchanged send counts, task digest and sender holds, and an
empty retry queue before starting the new worker. Verify active mailbox monitoring
and read-only public CLI task/receipt queries afterward. Do not test by sending to
creators or replaying historical failures.

The migration records a per-sender cutoff: only original send attempts created
after rollout are eligible. A nullable-add/backfill/non-null sequence preserves
existing holds. On any maintenance failure, leave API and worker stopped rather
than restarting old code that cannot enforce the new retry reservations. Keep
the private backup for reviewed recovery; do not automatically drop the new table
or erase sender holds.
