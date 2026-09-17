# Outreach task development checkpoint

Historical checkpoint for the original button-response release. Current
plain-text/IMAP replacement: [inbox-monitor.md](inbox-monitor.md). The Yes/No
contract below is retired by migration 0007, not the current implementation.

The backend is deployed for restricted SMTP acceptance testing (2026-09-17),
not yet a published CLI release. Existing `fmg email`
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

## Restricted deployment — 2026-09-17

- Source revision `61c001b`; image `fmg-agent:outreach-61c001b`.
- Checkout `/opt/fmg-agent-outreach-61c001b`; API healthy, Worker running;
  `0006_outreach` applied successfully.
- Before migration, database and previous service environment saved under
  `/var/backups/find-me-gamer-agent/outreach-61c001b-20260917T043133Z/`.
  Database dump also uploaded to the dedicated S3 backups/agent prefix.
- SMTP now enabled with a server-side allowlist containing only the explicitly
  approved internal test recipient. Do not remove this restriction without user
  authorization. The credential is not in this repository.
- Public callback origin is `https://44.233.174.193`.
- Local regression: 132 passed, one opt-in container test skipped; includes real
  PostgreSQL/Redis/Worker and local SMTP capture. Go tests/vet passed.
- Created Yes task `0320ee9a-fde6-4ef2-86f3-39d2c7c35979` and No task
  `31d83405-3e06-4a33-a77f-da89a2078c34`; both await explicit draft approval,
  each contains one test recipient. No task emails sent yet.
- Both local read-only dashboards successfully read the cloud drafts.
- Next: user reviews drafts, confirms start, then the recipient confirms each
  Yes/No link; verify independent recorded responses and dashboard statistics.
