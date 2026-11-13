# FMG CLI / Skills 0.8.9 — Read the full Inbox

Agents can now list the actual Inbox and read individual messages for both
`liminal` and `second`, including new threads and mail not associated with an FMG
task. Sent access and existing server reply commands remain compatible.

```sh
fmg email inbox --mailbox liminal --limit 20
fmg email inbox --mailbox second --limit 20
fmg email inbox --mailbox liminal --cursor NEXT_CURSOR
fmg email inbox --mailbox liminal --id MESSAGE_ID
```

`GET /v1/email/inbox` uses the same explicit mailbox-wide `email:read` permission
as Sent. No token permissions are automatically broadened. Lists and detail use
read-only IMAP and BODY.PEEK; they do not mark read, send, move/delete messages,
change monitor cursors or alter tasks, safety holds, queues or send pacing.

Lists scan at most 50 UID positions per page (default 20), newest UID first.
Deleted messages may leave short/empty pages with a next cursor. References bind
mailbox, account, folder and UIDVALIDITY; Inbox IDs are not FMG server reply IDs.
Headers include Reply-To and References. Detail reads retain the existing 128 KiB
MIME limit: larger messages report `body_omitted=true`, and attachments are not
exposed. This reads Inbox, not all mail folders or Junk.

Inbox and Sent share two read slots per API process so slow IMAP reads leave API
capacity for sending/status requests. Busy responses are retryable 503 with a
two-second retry hint. Skills describe bounded read retries, source classification,
body limitations, ID distinctions and CRM maintenance without inventing links.

## Validation

- New backend endpoint and CLI tests failed before the implementation was added.
- Focused Inbox/Sent, authentication, mailbox, sending/archive and monitoring
  regression tests: 109 passed; seven existing PostgreSQL-only cases skipped in
  the local SQLite environment. No database schema changed.
- Go tests/vet and both Skill validators passed. Release acceptance additionally
  checks actual downloaded packages, checksums, installer and version markers.
- Production acceptance must read list/detail for both Inbox and Sent with a
  short-lived read-only token and revoke it afterward; do not print mail content.

## Safe deployment

Build an API image derived from the exact running API image, changing only
`email/routes.py`, `email/sent.py` and the new shared `email/folders.py`.
Preserve all other production fixes and dependencies. No worker/monitor/dispatcher
recreation or database migration is needed.

Stage a temporary API replica, confirm readiness and both mailbox reads, then
gracefully reload the proxy to it. Drain the old API without force-killing requests,
replace only the canonical API, reload back and drain the temporary replica.
Verify unchanged worker/monitor/dispatcher container identities/start times,
mailbox credentials, runtime gates and existing token permissions. Live mail
progress may legitimately change; do not reset it to a snapshot.

## Upgrade

```sh
fmg upgrade --tag fmg-v0.8.9 --skills
fmg version
fmg auth check
```

Re-read both installed Skills and `fmg-api/references/email.md`. The two external
Agents upgrade at a safe command boundary, retaining current task IDs, cursors
and idempotency keys. Upgrading does not resume batches or authorize sending.
