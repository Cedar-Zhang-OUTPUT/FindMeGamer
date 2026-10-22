# FMG CLI / Skills 0.8.4 — Plain-text campaigns and random send pacing

Authorized scope, 2026-10-22: deploy both current campaign templates without
images, apply independently timed random 8/9/10-second send cooldowns to every
mailbox, and publish synchronized CLI/Skills. No test email, batch start, resend
or enrichment is authorized by this release. The user explicitly declined a new
persistent pause; preserve runtime gates and existing sender safety unchanged.

## Contract

- `liminal-private-outreach` is string version `2`; `thieves-outreach` is `3`.
  Both render a single `text/plain` MIME part without HTML or image attachments.
  Subject, body and all four personalization variables are unchanged.
- Historical frozen drafts, sent messages and unknown receipts are not rewritten.
  To remove images from an existing draft, prepare a current-version replacement
  and obtain fresh approval. Generic `game-outreach` v5 and retired Hotmail
  `liminal-outreach` v7 are unchanged.
- Every positive legacy pacing setting now selects a uniform random cooldown
  from `[8,9,10]` after each transport outcome. Shared PostgreSQL locks and durable
  gates cover direct sends, both mailbox worker slots and retries. Mailboxes are
  timed independently. Polling does not redraw or shorten the saved cooldown.
- Discovery reports minimum `send_interval_seconds=8` and additive
  `send_interval_choices_seconds=[8,9,10]`. Actual intervals may be longer due to
  dispatch/network time; this is not an exact 8/9/10-second scheduler or a promise
  of delivery/provider acceptance.
- CLI protocol remains compatible. Four platform binaries and both Skills are
  bundled together. Upgrading does not authorize sending or release a hold.

## Verification

The prior pacing full regression passed **616 tests, one skipped** using isolated
PostgreSQL/Redis, including dual-Agent and resource-budget cases. After template
changes, the non-integration backend regression passed **540 tests, nine skipped,
59 deselected**. These are separate runs, not additive unique test counts.
Tests exercise all three cooldowns, immutable polling, independent mailboxes,
failed/unknown outcomes, old MIME reproducibility, and exact new body equivalence.
No real SMTP/IMAP/Gemini calls were used for these regression tests.

The release also requires actual installer/checksum acceptance, Go test/vet,
both Skill validators and offline verification inside the production image.
The separately authorized SMTP login-only check returned 235 for both `liminal`
and `second`; no message was sent. Authentication success does not guarantee
recipient delivery or establish the provider's future policy decisions.

## Scoped deployment

Private artifacts and rollback configuration snapshots:
`/opt/fmg-text-pacing-20261022/`. Image `fmg-agent:text-pacing-20261022` derives
from the currently deployed `fmg-agent:task-monitor-20261021`, replacing only
configuration defaults, mailbox discovery, pacing/send hint code and the two
template JSON files. This preserves the deployed IMAP, Sent-copy and task-monitor
fixes. The enrichment worker and its diagnostics image are not restarted.

Before cutover, require no in-flight sends, send leases, unattempted recipients
in active tasks, queued retries or mail queue entries. Save private image/config
identities and database fingerprints. Gracefully stop API admission, dispatcher,
monitor and both mail workers; never force-kill or clear a lease. Recheck after
drain, then start those five roles using the final Compose overlay. No schema
migration, credential change, approval transfer, queue purge, runtime release or
sender-pause write is performed.

Acceptance compares sends, historical preview fingerprints, task states, runtime
gates, sender safety and private configuration before/after. Require actual role
readiness and current rendering/pacing on every switched role, plus unchanged
enrichment container identity. Keep the final Compose overlay last in future
operations; configuration snapshots contain secrets and must remain private.

After release, clients can run `fmg upgrade --latest --skills`, verify
`fmg version` / `fmg auth check`, and reload both installed Skills. Existing tasks
are not restarted by this upgrade.
