# Confirmed nonexistent recipients — 2026-10-12

This backend-only change retains CLI/Skills 0.7.4 and the existing frozen templates, task revisions and approval scope. No database migration is required.

- Failed DSNs with `5.1.1`, `5.1.3` or the existing `invalid_recipient` classification exclude that address for the same sending mailbox. Historical `5.1.3` records previously classified as generic delivery failures are recognized without rewriting history. Delayed notices are not hard failures.
- Confirmed nonexistent addresses no longer count toward the sender's three-distinct-final-retry-failures/15-minute hold. Other failures and immediate provider-rate-limit holds keep their existing behavior.
- A queued retry is cancelled if a later DSN confirms its recipient is nonexistent, including a final preflight check. Failed retries are not requeued and unknown deliveries are never resent automatically.
- New approved sends to a known nonexistent address produce an idempotent `failed` receipt with code `email_recipient_invalid` and `diagnostics.transport_attempted=false`. No transport request, pacing reservation or usage charge occurs; other recipients in the batch continue. Existing receipts remain readable and immutable.
- Deployment retains the current sender hold while replacing API and worker, with a PostgreSQL backup and before/after state/queue snapshots. The separately authorized release resumes only existing queued retries; it does not approve new batches or requeue already-failed retries.

## Verification

- Reproduced six failing regression cases before implementation, including the third nonexistent recipient causing a sender hold, duplicate delivery to a known bad address, late-invalid queued retry and `5.1.3` classification.
- Full backend suite: 299 passed, one opt-in local Docker test skipped because Docker remains stopped. Real isolated PostgreSQL, Redis, CLI/worker restart, local SMTP and global pacing tests included. One preexisting Starlette/AnyIO deprecation warning remains.
- The old CLI/worker integration fixture depended on elapsed test time accidentally clearing the default five-second pacing gate. Its unrelated recovery/uncertain-delivery fixture now explicitly uses zero cooldown; dedicated real five-second PostgreSQL pacing tests are unchanged.
