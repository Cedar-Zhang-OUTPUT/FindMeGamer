# Outreach task development checkpoint

This change is local development, not a deployed release. Existing `fmg email`
commands remain supported for individual/special-purpose sending.

## Implemented contract

- `outreach task create --input FILE --idempotency-key KEY` atomically stores a
  frozen template and all personalized recipient drafts in `awaiting_approval`.
- `task get ID` / `task list` read owner-scoped records using `email:send` scope.
- `task start ID --revision REV --confirm` requires explicit approval of the
  frozen revision and SMTP preflight. It queues durable work, not an HTTP batch
  SMTP loop. Existing worker dispatcher discovers unsent recipients.
- Single-send reservations ensure one SMTP attempt per recipient preview even
  with duplicate worker deliveries. Interrupted SMTP remains unknown, not retried.
- Different task recipients have independent random callback credentials. GET
  `/v1/outreach/respond/TOKEN?choice=yes|no` displays confirmation only; POST
  records the choice. Same choice is idempotent; conflicting second choice gets
  409. It does not change another recipient or another task's invitation.
- Shared scope is the CLI token owner, not an unauthenticated public task list.
- The local Skill dashboard is loopback-only, read-only and polls via the installed
  CLI. Gateway credentials never enter browser JavaScript. All recipients have
  full plain-text draft previews; the table displays 20 rows per page.
- SMTP acceptance, failure and unknown delivery are separate from Yes/No response.
  Response rate uses confirmed responses among SMTP-accepted rows / accepted rows.
  Inbox replies, opens, delivery guarantees and completed cooperation are not inferred.
- Changing drafts uses a new unapproved task and new review; existing snapshots
  are immutable. Do not approve both the original and replacement.
- Excel exports now use the agreed nine-column schema, with five-part evidence,
  gameplay relationship, campaign assessment, collaboration suggestion and AI
  limitations in the Match rationale. See the research Skill's files reference.

## Validation

Tests cover isolated recipient callbacks, GET safety, duplicate/conflicting
responses, token ownership, explicit approval, concurrent idempotent creation and
delivery, unknown outcome protection, SQLite migration, PostgreSQL migration,
compiled CLI -> HTTP -> local SMTP capture, local dashboard access, and real
Redis/Celery batch execution. No upstream models or real email recipients used.

## Deployment prerequisites / remaining live acceptance

1. Back up the isolated agent database; migrate `0005_cost` -> `0006_outreach`.
   Existing email/provider tables and commands are retained.
2. Set `FMG_AGENT_OUTREACH_PUBLIC_URL` to the public HTTPS **origin**, with no
   `/v1` suffix; existing `/v1/*` proxy routing covers callbacks.
3. Configure company SMTP host, port, encryption, credentials and sender. A task
   made before the sender is configured needs recreation and new approval.
4. Deploy API and Worker from the same revision. The worker needs the same SMTP
   configuration. Publish CLI and both Skills together; dashboard files are
   bundled automatically by the existing release script.
5. Obtain a designated test recipient and explicit send approval before real
   SMTP delivery, public HTTPS confirmation and dashboard acceptance. Local
   capture tests do not prove public callback routing or inbox placement.

Not included: mailbox reply ingestion, in-place task editing, automatic retries
of uncertain deliveries, attachments, CC/BCC, or arbitrary template creation.
