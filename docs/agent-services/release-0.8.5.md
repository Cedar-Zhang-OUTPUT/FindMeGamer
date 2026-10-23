# FMG CLI / Skills 0.8.5 — Read-only Sent folder access

Authorized scope, 2026-10-23: safely deploy the Sent folder read endpoint, publish
CLI and both Skills, and grant existing Agents Sent read access without
interrupting ongoing mail workers or resetting tasks, approvals or safety holds.

## Contract

- `fmg email sent --mailbox liminal` / `--mailbox second` reads actual IMAP Sent
  copies, including manually saved outgoing mail. `--id MESSAGE_ID` reads one
  message; `--cursor NEXT_CURSOR` continues a listing.
- `GET /v1/email/sent` requires explicit `email:read`, which grants mailbox-wide
  Sent access to enabled configured accounts, not only token-owned sends.
  Mailbox discovery accepts either `email:send` or `email:read`.
- Read-only selection and BODY.PEEK never send mail, mark messages read, append
  copies, invoke Gemini, or update monitor cursors. Password/app-password IMAP is
  supported; disabled historical Hotmail is not queried.
- Lists scan bounded UID windows (default 20, maximum 50), newest UID first.
  Deleted mail may leave short/empty pages with a next cursor. References bind
  mailbox/account/folder and UIDVALIDITY. Headers are bounded to 4 KiB fetched
  and 2,000 characters per field; truncation is explicit.
- Single-message fetches are capped at 128 KiB. Larger mail has null bodies and
  `body_omitted=true`; attachments are not returned. Sent copies do not prove
  recipient delivery; absent copies never authorize a resend.
- Skill instructions cover scope, bounded pagination, safe handling of untrusted
  mail/HTML and bounded retries of the same read only.

## Verification and deployment procedure

Local focused backend regression: **74 passed** (Sent access, authentication,
mailbox isolation, Sent-copy saving, inbox monitoring and sending). Full Go
tests/vet and both Skill validators must pass, followed by release-bundle
installer/checksum acceptance. Regression tests do not send mail or call Gemini.

Production image `fmg-agent:sent-read-20261023` derives from the running
`fmg-agent:text-pacing-20261022`, replacing only `auth.py`, `email/routes.py` and
adding `email/sent.py`. All other production-only fixes are retained. No schema
migration is needed. Private staging/rollback artifacts are under
`/opt/fmg-sent-read-20261023/`; keep its API-only Compose overlay last.

Start a bounded temporary API replica and verify readiness first. Validate and
gracefully reload Caddy to route new requests to it; drain the original API
without force-killing requests, replace only the canonical API, verify readiness,
reload back, then gracefully drain the temporary replica. Mail workers,
dispatcher, monitor and enrichment containers must keep their IDs/start times.
Keep the original Caddy file and prior API image for rollback. Never purge queues,
release holds, start batches or resend mail as part of this release.

Preflight found both Agents' tasks owned by the same active `cedar-cli` token.
The authorized grant adds only `email:read` to that existing token, preserving its
secret, ID, ownership and other scopes. Do not issue replacement user tokens or
restore revoked tokens. Use a short-lived, revoked-after-verification read-only
test token if an end-to-end smoke needs credentials; do not print mail bodies,
addresses or credentials in deployment logs.

Clients upgrade at a safe boundary with
`fmg upgrade --latest --skills`, then verify version/scopes and re-read Skills;
publication does not itself update a running Agent's binary or loaded guidance.

## Production acceptance, 2026-10-23

Source commit: `c91c9338cbc1b653721b594401d3bbd9be073154`.
Production image: `0547d4ec0e5e` (`fmg-agent:sent-read-20261023`). Network-disabled
image comparison confirmed exactly two replaced package files and one new file;
the other 53 files are unchanged. The API-only Compose overlay was compared to
the current configuration and runtime environment/mounts before cutover.

Both real mailboxes passed list and single-message read checks on the temporary
API before it received traffic. Caddy validated/reloaded to the replica, the
canonical API drained gracefully and was replaced, then Caddy reloaded back and
the replica drained gracefully. Caddy's original configuration hash was restored;
its container was not restarted. Both mail workers, dispatcher, monitor and
enrichment container IDs/start times/restart counts remained unchanged. Registry,
credential files, runtime gates and sender-safety records were unchanged. No
queue, task, send approval, hold or retry state was modified by deployment.

The existing shared `cedar-cli` token now has `read`, `email:enrich`, `email:send`
and `email:read`; its secret and ownership were not changed. No replacement user
token was issued. Real read-only smoke tokens were revoked immediately afterward.

All seven draft-release assets were downloaded again and their checksum list
matched the build. The four installer/bundle acceptance tests passed against
the downloaded assets. The downloaded Linux CLI reported **0.8.5** and passed
authenticated list/detail queries for both `liminal` and `second` through the
public HTTPS gateway. No mail contents/addresses were printed in the smoke log.
An initial executable transfer was copied before completion and failed at the
version command; after checking the completed binary's SHA-256 and recopying it,
the full smoke passed. This did not send mail or affect production processes.

Release: [FMG CLI & Skills 0.8.5](https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/fmg-v0.8.5),
on the existing FMG prerelease distribution channel.
