# Threaded reply API and rollout

Implemented locally on 2026-11-03. No production deployment or live email is implied by this document.

## API contract

All routes require `email:send`, restricted to the token owning the original send and preview:

- `GET /v1/email/replies/{server_reply_id}`: original body/sender/subject, kind, mailbox, task/creator/source/root-send linkage and stored threading headers.
- `POST /v1/email/reply-previews`: required `reply_id`, `mailbox_id`; either `template_id` + string `template_version` + `variables`, or `text` + `text_confirmed:true`. `recipient_mode` defaults to `sender`; `reply_to` requires exactly one valid address. No To/subject/header overrides. Custom plain text max 50,000 characters; template values single-line max 300 characters.
- `GET /v1/email/previews/{id}`: immutable full draft. Reply context includes original incoming text and sender, original Message-ID, Reply-To alternatives/discrepancies, source send/task/creator, selected recipient mode.
- Existing `POST /v1/email/sends` with preview ID, confirm=true and Idempotency-Key. Same preview/key returns existing receipt. Unique preview and token/key constraints prevent duplicate attempts across processes. Unknown remains unknown on replay. Mailbox safety, maintenance and pacing gates remain authoritative at send time.
- `GET /v1/email/receipts?idempotency_key=KEY`: token-scoped lookup when the client lost the send ID. A 404 is not evidence that an in-flight write cannot reserve later. Existing `/sends/{id}` remains supported.
- `GET /v1/email/reply-history?task_id=ID&creator_id=ID&limit=10&cursor=ID`: creator optional, limit1–20, send-attempt creation-time cursor order with send-ID as a tie-breaker. Outbound full snapshot plus receipt. Task detail and summary include `outgoing_reply_count` and `reply_history_url`; invitation delivery statistics remain separate.

Receipt adds `message_id`, `recipient`, `reply_id`, `idempotency_key`, `sent_at` and `sent_copy`. `sent` is provider acceptance. `failed` and `unknown` stay distinct; archive failure never changes accepted transport. `sent_at` records acceptance observation for new replies; null for legacy sends whose exact time was not separately recorded. `sending` is transient; timed-out reservations use the existing recovery-to-unknown mechanism. Different previews of the same incoming reply are separate drafts; Agents must coordinate ownership.

## Template and compatibility

`thieves-demo-access-reply` v1 is stored separately from invitation templates. Source: Feishu wiki CxtvwHnghi9bLbkoUytc3eydnBb, document DjdIdpybMoP4HPxq7q0cNKQencg, revision115. Only creator_name substitutes into the original plain-text body. Subject is Re: plus incoming subject, without stacking Re: prefixes. Registered reply versions are immutable files; new wording requires a new file/version mapping.

New incoming human records store Message-ID/References/In-Reply-To/Reply-To in diagnostics.thread_headers. Existing records remain intact. Legacy preview creation may fetch headers only from the same mailbox (read-only SELECT + BODY.PEEK), matching the stored Message-ID hash and sender, with bounded search. No result means reply_headers_unavailable, not a guessed thread. Duplicate/invalid/missing Message-ID means reply_message_id_missing. No schema migration; source and outbound snapshots reuse existing JSON columns. No reply display is added to the delivery-only dashboard.

## Rollout checklist

1. Verify tests and build matching CLI/Skills; preserve unrelated dirty changes in the workspace.
2. Safely deploy API, inbox-monitor code (to collect new headers), and any sending/retry process loading the new allowlist logic. Do not restart an in-flight sender; inspect active work and use the existing drain/maintenance procedure.
3. In the protected mailbox registry add `"allowed_reply_templates":["thieves-demo-access-reply"]` only to `second`, retaining its existing `allowed_templates`, credentials, Sent-copy settings and identity. Do not edit either invitation template. Custom replies require an owned human incoming record and explicit body confirmation.
4. Older binaries reject this new registry field: rollback binaries and configuration together. Until the allowlist is added the versioned template correctly remains blocked. Existing registry files without the field load as empty allowlists.
5. Deploy reply-capable CLI and both Skills. No new scopes are required for the current token's owned replies. Do not silently share another token's replies or expand mailbox-read permissions.
6. Validate read-only ownership/preview and full recipient/thread fields. Only send a live test after recipient/content approval. Retain actual sender safety and pacing; do not resume any paused batch as part of release.

Transport threading headers are emitted by the shared MIME builder used by SMTP and Graph and reproduced in Sent copies. Email clients may still choose their own display grouping; headers cannot guarantee a particular UI layout.


## Validation completed locally

- Reply/send/compact-task/Sent-copy focused regression: 41 passed, including PostgreSQL concurrent submission and unknown receipt reconciliation. After adding chronological pagination, reply + compact-task checks: 24 passed. These suites overlap; counts are not additive.
- Full isolated PostgreSQL17 / Redis7 run: 661 passed, 1 skipped; two reported failures were investigated. One was the new legacy-header test's invalid SQLite test setting, corrected and passed in the focused rerun. The other is the existing native-process resource sampler: it attempts host `ps` on a PostgreSQL PID inside Docker, which is a different PID namespace. No resource-capacity result is claimed for that test.
- Go `go test ./...`: passed, including versioned-template lookup, reply-preview validation, custom-body confirmation and read-only key reconciliation.
- Both Skills pass skill-creator validation. Local four-platform CLI/Skills candidate bundle and installer/upgrade checks: 4 passed, with authentication preserved in isolated test directories.
- Only local simulated SMTP/IMAP and provider stubs were used. No production change or real mail/Gemini call occurred.

The source body retained in reply history is the existing monitor-stored text, subject to its existing size limits. Reply previews are not send approval. Deployment still requires the coordinated API/monitor/send-worker upgrade and reply-template allowlist addition described above.
