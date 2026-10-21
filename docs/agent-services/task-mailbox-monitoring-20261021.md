# Task-bound mailbox monitoring hotfix

## Cause and scope

After the LIMINAL Private Email migration, `GET /v1/outreach/tasks/{task_id}`
still passed process-global mail settings to `monitoring_status`. Consequently,
both full and summary reads reported the retired Hotmail INBOX cursor (last
success 2026-10-21 06:08:07 UTC), not the task's actual mailbox. Production
LIMINAL and No Rest monitors were continuing to synchronize successfully.

The handler now resolves the task's immutable `mailbox_id` through the current
registry. Disabled historical mailboxes return `disabled`; removed or unresolved
identities return `unavailable` with a specific error, never the legacy cursor.
Unconfigured active mailboxes remain `not_configured`. Invalid registry files
still fail explicitly instead of appearing healthy. Ownership checks are unchanged.

This is an API response fix, not an IMAP authentication or worker repair. No
credentials, mailbox identities, frozen drafts, sending gates, automatic retry
policies or monitoring cursors are rewritten. CLI/Skills 0.8.3 already consume
the response and need no new package for this hotfix.

## Validation

- Seven new regression cases reproduced the stale/global-cursor bug before the
  implementation and passed afterward. They cover two independent mailboxes,
  full/summary reads, live registry changes, disabled/missing/unbound identities,
  absent IMAP configuration and invalid registry handling.
- Focused regression: 49 passed, eight PostgreSQL-dependent cases skipped in
  that initial run. Full isolated PostgreSQL/Redis regression is recorded below.
- Independent source/test review found no blocking issues. Deployment review
  required read-only verification transactions and suppression of the existing
  GET recovery hook in the isolated diagnostic subprocess only; both were added.
  The running API's existing recovery behavior is unchanged.
- Built production image imports successfully with networking disabled; its
  installed `outreach.py` SHA-256 matches the tested source:
  `3f32bb120920fb080c4c7a9351379d6fc47ddc8dab8e4ca6d06efcaa370fecdd`.

## Deployment

Staged image: `fmg-agent:task-monitor-20261021` (`5a6d45fca326`), based on
`fmg-agent:liminal-private-20261021`. Only the installed `outreach.py` is replaced.
Restricted deployment metadata and the API-only overlay are in
`/opt/fmg-task-monitor-20261021/` on the production host. Keep this overlay last
after the LIMINAL migration overlay until a subsequent full image incorporates
the fix. The previous API image remains available for an explicitly reviewed rollback.

The switch checks zero in-flight sends, stops only API gracefully and uses
`docker compose up -d --no-deps api`. Verification checks API health, the source
hash, unchanged IDs/start times/images for every other role, unchanged mailbox
registry hash and runtime gates. It exercises full and summary handlers for
existing LIMINAL, No Rest and retired Hotmail tasks against production data,
inside a read-only diagnostic process (not an HTTP authentication test).

No real email, new batch, resend or paid enrichment call is used for acceptance.

## Acceptance result

- Full bare `pytest -q` in isolated native PostgreSQL 17 / Redis 8.10.1 with
  the compiled CLI: **607 passed, one optional container-rehearsal skip**,
  655.62 seconds. Existing AnyIO deprecation warning only. These local test
  servers were shut down after completion; no production services were used.
- API-only cutover completed around 2026-10-21 07:37 UTC. Immediately before
  switching, zero sends were in flight; both global runtime gates stayed enabled.
- The healthy deployed API passed all six existing-task handler checks:
  LIMINAL and No Rest `active`, retired Hotmail `disabled`, in both full and
  summary mode. The observed active cursor timestamps were 07:36:35 UTC for
  LIMINAL and 07:36:36 UTC for No Rest, with no monitor errors.
- Source hash matched. Every non-API role retained its container ID, start time
  and image; registry hash and runtime gates were unchanged. No sender or
  monitor process was restarted. Public HTTPS health verification is recorded
  separately from the in-process handler checks.
