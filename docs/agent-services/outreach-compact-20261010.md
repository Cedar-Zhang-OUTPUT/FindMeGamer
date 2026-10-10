# Compact outreach task responses — 2026-10-10

## Incident and fix

The fifth 50-recipient LIMINAL task produced approximately 20.97 MiB per status
query; 21,644,000 bytes were repeated inline signature/banner image data. The
CLI caps responses at 32 MiB and its HTTP timeout is 30 seconds. The generic
"incomplete or too large" error does not distinguish a body read failure from
the size cap: this task was below the cap but unnecessarily expensive to poll.

Task create, idempotent create replay, get and start responses now omit
`signature_png_base64` and `footer_png_base64` from each recipient's `message`.
They retain subject, plain-text/HTML draft, addresses, format, task revision,
statistics, replies, delivery diagnostics, monitoring and sender safety.

Each recipient exposes `preview_id`. Fetch the complete owner-scoped frozen
preview only when needed:

```sh
fmg email preview --id PREVIEW_ID
```

This uses the existing `GET /v1/email/previews/{preview_id}` endpoint. No CLI
upgrade or dashboard change is required: the dashboard previews `message.text`.
The response is projected into a new dictionary; stored drafts and actual
outgoing MIME images are not modified. No migration, template revision change,
approval, sender-hold release, or task restart is involved.

## Regression coverage

- Real 50-recipient LIMINAL v7 responses remain below 1 MiB for creation, replay,
  status query and approval. Approval in tests uses isolated local data only.
- Complete previews retain both images and enforce owner isolation.
- Querying a blocked task keeps it blocked and creates no send attempts.
- Local delivery still receives the exact original image-bearing payload.
- Historical single-image drafts and new banner drafts remain unchanged.

Deployment acceptance must also query the existing paused fifth batch with the
published CLI, verify its unchanged revision/pending count and stored snapshot
hashes, check API health and reply monitoring, and confirm no test sends occurred.

Full local verification uses an isolated PostgreSQL test database, an ephemeral
loopback Redis on port 55440, and the published 0.7.3 CLI. Set
`FMG_AGENT_EMAIL_SEND_INTERVAL_SECONDS=0` in this test invocation only:
`test_cli_email_worker_restart` tests delivery outcomes, not elapsed pacing, and
otherwise attempts its next local SMTP fixture message before the production
five-second cooldown expires. Dedicated SQLite/PostgreSQL pacing tests explicitly
set five seconds and still exercise the real gate. Production pacing is unchanged.
The opt-in container smoke test remains skipped because local Docker is stopped.
