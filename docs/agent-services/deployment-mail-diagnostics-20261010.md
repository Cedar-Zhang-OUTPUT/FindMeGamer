# Microsoft Graph send diagnostics — 2026-10-10

- Deployed application source `3bd915e`, image
  `fmg-agent:diagnostics-3bd915e`, checkout
  `/opt/fmg-agent-diagnostics-3bd915e` on the existing EC2 host.
- Changes are diagnostic-only. Non-202 Graph responses retain allowlisted error
  codes/prose, normalized Retry-After seconds, request/client correlation IDs,
  response date and observed timestamp. Unknown prose is withheld; unknown bounded
  error identifiers are fingerprinted, never logged raw. No raw response body,
  credentials or mail content is retained in diagnostics.
- Added nullable `email_sends.diagnostics` via `0009_mail_diagnostics`. Existing
  receipts expose null diagnostics, not fabricated historical explanations.
  Owner-scoped single receipts and outreach recipient JSON expose the new field.
  Structured `graph_mail_response` logs omit provider prose entirely.
- No automatic retry, resume, provider backoff or new send action was introduced.
  Sender `ontologyplay@hotmail.com`, Graph transport, empty recipient allowlist,
  five-second shared gate and IMAP monitoring configuration are unchanged.
- Before maintenance: no queued/running enrichment, in-flight sends or approved
  pending sends. Backed up private service configuration, runtime metadata and
  agent DB to
  `/var/backups/find-me-gamer-agent/diagnostics-3bd915e-20261010/`.
  Only agent API/Worker were stopped/recreated; OAuth volumes retained. Rollback
  restores image `fmg-agent:pacing-72ca386`; additive schema may remain.
- Verification: full local Python suite **242 passed, 8 skipped** (integration
  prerequisites); uncached Go suite passed. Final production image with isolated
  PostgreSQL 17 **23 passed**, covering migration preservation, real pacing locks
  and offline Graph diagnostics. One pre-existing AnyIO deprecation warning.
  External provider I/O was simulated; no real email was sent for acceptance.
  Temporary PostgreSQL test container was stopped/removed.
- Post-deployment at `2026-10-10T05:25:55Z`: public TLS health `ok`, API healthy,
  Worker running, schema head `0009_mail_diagnostics`; historical send totals
  unchanged at 94 accepted / 53 failed. IMAP active, last successful sync
  `2026-10-10T05:25:24Z`, no error.
- Current task `a01c5ba7-ece3-486b-ad67-01469141336d` remains `blocked` (paused):
  8 accepted, 38 failed, 4 unattempted, 0 in flight, 0 attempts since pause.
- Existing CLI passes additive JSON through without a binary upgrade:
  `fmg email receipt <send-id>` or `fmg outreach task get <task-id>`.
  This does not identify the cause of historical 429s: their original provider
  details were discarded. A future explicitly approved send failure can provide
  new evidence; no test send or batch recovery has been authorized here.
