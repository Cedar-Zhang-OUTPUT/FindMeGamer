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

Production acceptance and published release details will be recorded after
verification. Clients upgrade at a safe boundary with
`fmg upgrade --latest --skills`, then verify version/scopes and re-read Skills;
publication does not itself update a running Agent's binary or loaded guidance.
