# Plain-text outreach and real replies

Implementation checkpoint, not a deployment record.

## Contract

- New drafts use plain text only: `game-outreach` version 3, `liminal-outreach`
  version 2. Fixed template prose is retained; only declared variables change.
- Retired HTML versions cannot create new drafts. Previously approved snapshots
  are not silently rewritten: unsent old snapshots require recreation and review.
  Existing sent history and SMTP idempotency receipts remain intact.
- Yes/No routes are removed (404). Migration `0007_inbox` removes callback-token
  and response columns, adds `email_replies` and `inbox_cursors`. Old emails cannot
  be recalled; their old links cease working after deployment.
- A separate worker thread polls IMAP over verified TLS using read-only SELECT
  and BODY.PEEK. It fetches headers, and text only for likely FMG replies/reports;
  attachment payloads are not downloaded. Nothing is marked read or deleted.
- In-Reply-To/References must identify an FMG Message-ID. Human/automatic replies
  additionally require the sender to match the original recipient. Delivery
  reports may instead quote the original message headers. No subject guessing.
- Message-ID deduplication prevents repeated synchronization from inflating
  counts; the UID cursor advances only after processing. UIDVALIDITY changes
  restart the bounded lookback while preserving deduplication.
- Polls process at most 100 messages, inspect at most 64 MIME parts per message,
  retrieve at most 64 KiB per text part, and retain at most 50,000 body characters.
  Bodies may therefore be excerpts. Unrelated message bodies are not stored.
- `reply_state`: replied, automatic, bounced, no_reply. Header-based automatic
  reply detection is best effort, not proof of a human sender. Reply does not mean
  acceptance or completed cooperation. Different-address replies/new threads may
  remain unlinked rather than be attributed to the wrong person.
- `stats.reply_rate`: distinct human-replied recipients among SMTP-accepted rows
  / SMTP-accepted rows. Unknown deliveries are excluded from numerator and
  denominator; their replies remain visible. Null denominator produces null.
- `monitoring`: active/waiting/not_configured/stale/error, last_success and safe
  error code. No recorded reply is not proof of no mailbox reply, especially when
  monitoring is not active. `received_at` is the record's observation time.
- The read-only dashboard displays plain-text previews, real replies, filters,
  counts and monitor health. No automatic response interpretation or sending.

## Configuration and rollout

See `deploy/agent-services/env.example`. Set IMAP host, TLS port (normally 993),
username, client-specific password, folder, poll interval and initial lookback.
Do not assume SMTP credentials automatically enable IMAP. Keep credentials only
in the private service environment, never source control or Agent artifacts.

Mailbox UI was inspected on 2026-09-17: `imap.qiye.aliyun.com:993` SSL, mailbox
range 30 days. Existing client-specific credential successfully authenticated and
selected INBOX read-only from the development machine. No bodies were fetched in
this check. This does not establish cloud-network connectivity or live reply
ingestion acceptance.

Before rollout, inspect approved pending work, stop API and Worker, back up the
isolated database and private configuration, migrate 0006 -> 0007, and deploy both
from the same revision. Keep one worker parent running the inbox synchronizer.
The migration intentionally discards obsolete callback choices; rollback needs
the pre-migration backup. Preserve the current SMTP test-recipient allowlist.

Start with a designated, explicitly approved test send. Have its recipient reply;
check only that recipient updates, repeated sync stays deduplicated, and the
dashboard reads the actual reply. Do not send email just to test monitoring
without approval. Release the updated dashboard Skills together with the backend.

## Local validation

Regression includes PostgreSQL migrations, real local Redis/Worker and SMTP
capture, CLI -> HTTP -> dashboard integration, IMAP read-only/cursor/error
fixtures, reply isolation, duplicates, automatic replies and delivery reports.
It does not substitute for the approved real-mail reply test above.
