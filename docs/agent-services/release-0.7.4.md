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
