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

- A first explicit spam-blocking DSN queues **one** automatic resend, no earlier
  than 30 seconds after ingestion. The 10-second dispatcher and the mailbox-wide
  send gate can delay it further; the timer starts when the monitor discovers the
  DSN, not when the remote mail server originally produced it. The monitor still
  polls every 60 seconds. Initial bounces do not trip the sender hold.
- A resend uses a separate immutable child preview, the exact original sender,
  recipient, subject, text and images, and a new FMG Message-ID. A unique original
  send ID prevents repeated/copied DSNs and concurrent workers from scheduling
  more than one resend. A retry can never create another retry.
- Only a retry's explicit transport rejection or failed-delivery DSN counts as a
  final failure. At least **3 distinct recipient addresses with final failures
  observed within 15 minutes** trips `outbound_spam_blocked` for that sender.
  Acceptance without a DSN is not proof of delivery and is not counted as failure.
  Unknown outcomes are neither resent nor counted as explicit failure.
- A synchronous Graph 429 (`graph_rate_limited`) immediately trips
  `provider_rate_limited`, without retrying the rejected message.
- Initial invalid-recipient/mailbox-full/unknown-category DSNs are still recorded,
  but not automatically resent or guessed to be spam. Ordinary human replies do
  not trigger retries. A human reply before reservation cancels a pending retry.
- The sender hold persists across restarts, stops approved pending batches for
  that exact sender across access tokens, and rejects direct sends and new batch
  starts (`email_sender_paused`). Task API exposes `sender_safety` without
  exposing another owner's task contents.
- Queued workers recheck batch state at the reservation boundary. No new
  EmailSend is created for held/pending recipients. An already reserved/in-flight
  provider request cannot be recalled. Idempotent receipt replays remain available.
- There is **no automatic expiry, release, or batch resume**. Retries respect
  sender holds, blocked batches, revoked access, sender changes, preview expiry,
  the existing durable reservation and mailbox-wide cooldown. A restart recovers
  an interrupted retry as `unknown`, never as permission to send again.
- Migration `0011_bounce_retry` preserves existing holds and records a per-sender
  rollout cutoff (`retry_enabled_at`). Original sends before that cutoff cannot
  create automatic retries, even if their delayed DSNs arrive after rollout. No
  old bounce records are backfilled and no historical batch is restarted.

## Querying retry progress

Existing `fmg email receipt ID` and `fmg outreach task get ID` commands expose an
additional `bounce_retry` object: state, due time, final-failure time, retry send ID,
code/diagnostics and cancellation reason. Task stats include `retry_queued`,
`retry_sending`, `retry_sent`, `retry_failed`, `retry_unknown`, `retry_cancelled`.
Task recipients retain the original preview ID and draft, combine both attempts'
reply history, and present the latest attempt's transport/reply status. Historical
first-attempt receipts are not rewritten. Waiting retries keep the task in
`sending`, rather than prematurely declaring completion. A retry's `sent` still
means provider acceptance, not confirmed inbox delivery. Do not manually duplicate
a pending, accepted or uncertain automatic resend.

Retries run in the server worker; no client-side loop or CLI upgrade is needed.
This rule is an operational retry policy, not a guarantee that an antispam or
mailbox limit has been resolved. Explicit Graph throttling still immediately
pauses the sender and takes precedence over the 3-recipient threshold.

## Administrator release

Only after investigating provider restrictions, reviewing bounces, and receiving
explicit authorization: use the server's private Python environment/Settings to
open a transaction, obtain `fmg_agent.email.safety.locked(session, sender)`, clear
that row's `reason` and `paused_at`, and commit. This is intentionally not a
public Agent-accessible bypass. Do not expose DB credentials or OAuth tokens.
Releasing this sender hold does **not** restart any batch: the existing frozen
revision must still be explicitly approved through the start endpoint. Recently
observed final retry failures can trip the hold again; do not loop on release/retry.

Migration `0010_bounce_safety` only adds a nullable JSON column and a new table.
Backup before maintenance; keep old API/worker stopped during migration. Rollback
must not resume sending without retaining equivalent sender holds.
