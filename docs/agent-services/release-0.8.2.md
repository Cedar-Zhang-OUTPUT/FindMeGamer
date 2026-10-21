# FMG CLI / Skills 0.8.2 — IMAP parsing and bounded network recovery

User authorized publication and a monitor-only production cutover on 2026-10-21.
Do not restart the API, sending workers, dispatcher or enrichment worker.

## Changes

- PrivateEmail returns an empty literal, not NIL, for absent MIME sections.
  The old walker treated this as another text part until `mime_structure_limit`,
  surfaced as `imap_sync_failed`. Stop child enumeration for either absent form;
  retain valid empty bodies, attachment exclusion, nesting/part limits and cursor
  retry semantics. Do not skip messages or clear their failure without processing.
- CLI transport errors expose `recovery=retry_read` for GET/HEAD and
  `reconcile_write` for writes. No automatic CLI replay is introduced.
- Known HTTP rejection headers remain authoritative when their error body is
  interrupted: preserve status and auth/quota exit class, with no transport retry
  guidance. Raw provider/network error strings are not leaked.
- Both Skills specify at most three status-read retries, after 2/5/10 seconds.
  Persist a recovered result and continue the original authorized remainder.
  Exhaustion pauses new submissions; no outer-loop budget reset. Uncertain writes
  are reconciled separately; no automatic mail replay, new job keys, hold clearing,
  or treating 429/IMAP errors as local transport failures.

## Evidence and safety

- Before the fix, synthetic empty-literal and nested-MIME regressions failed;
  NIL compatibility remained passing. CLI recovery-field regressions also failed.
- Read-only production reproduction: second mailbox INBOX UID 16 and Spam UID 1
  both raised `mime_structure_limit`; nonexistent MIME sections had zero-byte
  literal bodies. Patched parsing of the same messages succeeded (4 and 6 parts)
  in a separate process, without ingestion, Seen changes or sends.
- Independent code review identified the broken HTTP-error-body boundary; a
  failing regression was added before fixing it. Final review found no remaining
  actionable issues. Five Skill consumption scenarios checked recovery, exhaustion,
  uncertain submission, unknown sending and HTTP/IMAP failures; start-idempotency
  wording was clarified after review.
- Initial backend suite without integration services: 513 passed, 67 skipped,
  14 setup errors (missing dedicated test PostgreSQL/Redis URLs), not acceptance.
  Isolated PostgreSQL 17/Redis 7 services were subsequently started for a full run.
- Full Go tests and vet passed. Four cross-built CLI archives plus Skills/install
  assets passed all four installer/bundle tests, including preserved authentication,
  checksums and installed Skill version markers. Both Skill validators passed.

This release does not grant new mail approval, restart paid enrichment or change
Gemini/backup working-tree edits.

## Production cutover

Only `fmg-agent-monitor-1` was gracefully stopped (exit 0, no forced kill) and
recreated with image `fmg-agent:imap-empty-section-20261021`, image ID
`b4523b8e58a3adfe6788e898ed6c1e3da9a6fa07f2a6e2e5015fd62cc61e9218`.
The production base inbox.py SHA-256 matched HEAD before replacement. New source
SHA-256: `e62444299e2c8f237fdcff5100a1c16db5d2326a737b6fd63ee7549ce4d4a573`.
The new image passed an offline, network-disabled MIME parsing check.

Preflight checked no in-flight sends/retries, exact current image, unchanged
environment/command/mounts/network and the complete existing overlay list. All
other role container IDs and start times, plus the private mailbox registry hash,
were unchanged after recreation. This instantaneous preflight does not claim
that existing approved workers cannot subsequently send; they were not stopped.

Deployment overlay and rollback metadata are retained at
`/opt/fmg-imap-20261021-DRvTdp/` (snapshot contains no credentials). Future Compose
operations must retain its last `compose.yaml` overlay until this fix is included
in the shared base image. Rollback uses the previous monitor image and the prior
overlay list; do not roll back databases, clear safety holds, or recreate workers.

At 2026-10-21 05:28 UTC, both mailboxes reported `active`, error null. Second
mailbox INBOX advanced from UID 6 to 59; Spam from 0 to 3. Its previously empty
reply store now contained 20 human, 1 automatic and 2 bounce records. These are
matched messages in configured monitored folders, not a complete count of unique
people or a scan of Archive/Trash. Existing deduplication and bounce policy remain
in force. No test mail, manual resend, new enrichment or safety reset was issued.

## Full regression environment note

The PostgreSQL 17/Redis 7 container-backed run completed with 592 passing tests,
1 optional image-rehearsal skip and 1 environment failure: the native resource
sampler queried a container PostgreSQL PID using host `ps`. This is the documented
mixed-namespace limitation in `multi-mailbox-docker-acceptance-20261017.md`, not a
code assertion failure. The isolated native rerun of that one case follows below.

The native resource/slow-enrichment case passed in 315.92 seconds on dedicated
loopback PostgreSQL 17 and Redis services, resolving that environment-only failure.
Combined coverage: 593 passed, 1 optional image rehearsal skipped. The existing
Starlette/AnyIO deprecation warning remains. Temporary test services were shut down;
the unrelated Supabase service and old FMG services were not touched.

## Publication acceptance

Source commit: `5d1e588e8f393f19de56241a9ca0b295d1433366` on `cli`. Unrelated
working-tree Gemini and backup changes were excluded. All seven uploaded assets
were downloaded again; six payload SHA-256 checks and the checksum-list comparison
passed. All four installer/bundle tests passed again on the downloaded archives.
Packaged Skill contents matched all 23 current source files. Published as the
`fmg-v0.8.2` CLI/Skills prerelease, without replacing the desktop-app latest release.

Clients should run `fmg upgrade --latest --skills`, verify `fmg version` and
`fmg auth check`, then re-read both installed Skills and `references/usage.md`.
The CLI reports recovery guidance; the Agent performs bounded read retries.
