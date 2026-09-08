# P7: Activity qualification and final sending

Local internal-Demo implementation. This unit uses existing settings, SMTP transport,
Redis limiter and Celery, with real Activity provenance. It never invents a MatchTask
or response token. Verification uses socket-free SMTP captures only; no live email,
provider/model call, push or deployment is authorized by these tests.

## Full batch qualification

`POST /api/v2/outreach/compositions/{id}/qualification` takes:

```json
{"excluded":[{"draft_id":"UUID","reason":"Need recorded evidence"}]}
```

It returns all original N members with actual sender address/name/Reply-To, actual
single recipient address, subject, full HTML/plain text, four values and their
sources, template version/hash, draft revision/current context, identity, sender
facts and per-member missing fields. Counts are `total_count`, `eligible_count`,
`repair_count`, `excluded_count`; `send_ready` requires at least one eligible member
and no unexcluded repair. Every exclusion is explicit and has a reason. No per-person
open/preview approval is required, and display filtering never shrinks qualification.

Current identity, selected email, confirmed name, recorded observation, completed
four slots, immutable template/game/hash and explicit sender facts are checked.
AI fit ranking or evidence of playing this particular game is not an extra gate.
SMTP public configuration and a stored credential must exist; qualification does not
probe or send, and cannot promise that the server will accept the credential.

Duplicate nonexcluded addresses require repair or explicit exclusion; never silently
merge people. For normal invitations, an existing queued/sending/sent/unknown Delivery
for the same Activity + platform + account ID blocks a new invitation, even across
compositions/request UUIDs. `blocking_delivery_id` and `already_invited` identify the
record. Identity revision is preserved for provenance, not used to bypass this rule.
Different activities remain independent; future explicit follow-up modes are not
blocked by a permanent account uniqueness constraint and are not implemented here.

`qualification_token` fingerprints the whole current result. `sending_account_token`
binds public host/port/encryption/username/From/Reply-To and credential presence, not
the password. Relevant edits or sending choices invalidate the old qualification.
Use A's explicit refresh/repair/facts workflow before confirming again.

## Final authorization and immutable history

`POST /api/v2/outreach/compositions/{id}/send-batches` takes `Idempotency-Key` and:

```json
{"request_id":"UUID","qualification_token":"64hex","excluded":[]}
```

Under the shared transaction write lock it recomputes qualification and freezes only
the exact eligible subset. A batch retains the full qualification including exclusions;
each ActivityDelivery retains one address, actual From/Reply-To, template/hash,
subject/HTML/plain text, four values, evidence and confirmation/identity snapshot.
Original RecipientSnapshot and discovery context remain unchanged. Later Library or
draft edits cannot rewrite the final content. Same durable request UUID/body replays
the same batch even after the short header cache expires; conflicting reuse fails.

Read using `GET /api/v2/activities/{id}/send-batches?limit=50&offset=0` and
`GET /api/v2/outreach/send-batches/{id}`. Delivery state is queued/sending/sent/failed/
unknown, with attempt, safe error code, retryability, timestamps and resolution notes.
`sent` normally means SMTP accepted, not proven delivered to the recipient's inbox.

Dispatch happens after commit. Queue503 means the record already exists: replay the
same final request/header to dispatch its queued Delivery IDs, never generate a new
request UUID as a recovery tactic. Worker row claims and leases prevent concurrent
or completed duplicate dispatch from sending again. Shared rate limiting defers via
the queue without SMTP submission or long sleeping while a database lock is held.

## Failure, retry and unknown outcome

`POST /api/v2/outreach/deliveries/{id}/retry` takes `{expected_attempt}`. A definite
failed delivery can retry its exact frozen content/address; a queued record may be
redispatched safely after broker failure. Retry does not adopt current Library edits.
Changing a failed email or body requires a fresh draft/qualification/final snapshot.
This new confirmation and retry of the old failure serialize on the same write lock;
an already active/sent/unknown invitation prevents the old failure from retrying too.

Disconnect/timeout after entering SMTP submission is `unknown / smtp_outcome_unknown`,
not an ordinary retryable failure. An expired sending worker is also unknown. No
automatic retry or normal Retry is allowed until an explicit verification:

```text
POST /api/v2/outreach/deliveries/{id}/resolve
{expected_attempt, outcome:"sent"|"not_sent", source_note:"how this was verified"}
```

This records operator source notes, time and attempt. `sent` is a manually verified
outcome (distinguishable through `resolution`), not fabricated transport evidence.
`not_sent` becomes a definite failure; it does not itself send anything. A later
explicit Retry is required. No inbox sync, automatic follow-up or resend of sent
messages is added. Existing legacy workers also stop automatic retry on the new
unknown transport error, while legacy CTA/template/response behavior remains intact.

New-mode MIME takes its exact HTML/plain text directly from the frozen snapshot,
with stable Delivery-based Message-ID. It adds no Yes/No, response callback, tracking
or markdown rerendering. Actual SMTP account identity is checked before submission;
a changed sending account fails without logging in or sending to the old snapshot.
Password-only correction may use the latest encrypted credential.

## Migration / verification boundary

Migration0017 adds Activity send batches/deliveries atop0016 without changing legacy
Match campaign tables. Populated downgrade refuses destructive history loss. Current
maintenance-window migration, not rolling old/new Worker compatibility, is supported.
Focused75tests passed, including30new B tests and old SMTP/MIME regressions.
One bounded independent review found the legacy public SMTP error projection omitted
the new unknown-outcome warning. Added that safe tuple and typed enum without changing
legacy resend policy; a new projection regression failed before the fix and passed
afterward, plus an existing HTTP worker test now checks the visible warning.

Final exported OpenAPI and complete isolated real-Redis suite: **2267 passed,
3 skipped, 0 failed**, 221.26s, 2026-09-08 (31 new B tests). One existing Starlette
deprecation warning. The three skips are the already deferred old-live-Writer
migration lock-order cases, outside maintenance-window operation. No second broad
review, provider/model request, live SMTP, push or deployment was performed.
