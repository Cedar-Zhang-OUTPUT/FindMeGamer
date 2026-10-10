# Delivery reports and sender holds

IMAP synchronization now discovers the server's Junk/Spam mailbox (`\Junk` or
common mailbox names) in addition to the configured INBOX. Unusual server names
can be explicitly added with `FMG_AGENT_IMAP_EXTRA_FOLDERS` (JSON list). Each
folder keeps an independent UIDVALIDITY/UID cursor. Initial scans are bounded to
the configured lookback (default 30 days), 100 messages per folder per tick.
Messages are read with BODY.PEEK and readonly SELECT: no mail is moved, marked
read or deleted. Only matching replies/DSNs are saved, never attachment payloads.
The existing primary cursor's health now represents the whole scan: a folder
discovery or synchronization failure reports an error, rather than a false healthy
status. Repeated folder copies are deduplicated by report Message-ID + send ID.

Machine-readable delivery reports retain action, status, bounded diagnostic text
and category on `email_replies.diagnostics`. Matching still uses the embedded
original FMG Message-ID, not a fuzzy subject or display name. Delayed/successful
delivery notices are automatic notifications, not failed delivery or human replies.
Only a top-level delivery-report envelope is classified as a DSN; an ordinary
reply containing an attached old report cannot trigger a hold.
Recipient/task API responses include diagnostics; existing dashboards already
display `bounced` and `stats.bounced`. A completed task with bounces is
`finished_with_issues`. Historical `sent` remains upstream acceptance, not delivery.

Safety defaults (server side, no CLI upgrade required):

- At least 3 distinct recipient addresses with explicit spam-blocking DSNs
  observed within 15 minutes trips `outbound_spam_blocked` for that sender.
  Copies/repeated reports for the same recipient do not inflate the count.
- A synchronous Graph 429 (`graph_rate_limited`) immediately trips
  `provider_rate_limited`, without retrying the rejected message.
- Invalid recipient/mailbox full DSNs and ordinary human replies do not trip
  the spam threshold. Unknown errors are not guessed to be spam.
- The sender hold persists across restarts, stops approved pending batches for
  that exact sender across access tokens, and rejects direct sends and new batch
  starts (`email_sender_paused`). Task API exposes `sender_safety` without
  exposing another owner's task contents.
- Queued workers recheck batch state at the reservation boundary. No new
  EmailSend is created for held/pending recipients. An already reserved/in-flight
  provider request cannot be recalled. Idempotent receipt replays remain available.
- There is **no automatic expiry, release, resume, or resend**. Migrating and
  backfilling existing Junk DSNs may conservatively establish a sender hold.

## Administrator release

Only after investigating provider restrictions, reviewing bounces, and receiving
explicit authorization: use the server's private Python environment/Settings to
open a transaction, obtain `fmg_agent.email.safety.locked(session, sender)`, clear
that row's `reason` and `paused_at`, and commit. This is intentionally not a
public Agent-accessible bypass. Do not expose DB credentials or OAuth tokens.
Releasing this sender hold does **not** restart any batch: the existing frozen
revision must still be explicitly approved through the start endpoint. Recently
observed spam reports can trip the hold again; do not loop on release/retry.

Migration `0010_bounce_safety` only adds a nullable JSON column and a new table.
Backup before maintenance; keep old API/worker stopped during migration. Rollback
must not resume sending without retaining equivalent sender holds.
