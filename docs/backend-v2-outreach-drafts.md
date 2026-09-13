# Locked template versions and independent personalization drafts

## September 13 personalization update

Draft editing is independent of generation and sending. The API remains
`PATCH /api/v2/outreach/drafts/{id}` with revision/context checks. Exactly four
single-line, escaped plain-text slots are accepted, including empty strings;
each is at most 600 characters. Saving an observation fragment without a final
period is allowed. Complete strict values produce `succeeded`; incomplete values
produce `needs_repair`. Source/SMTP warnings do not prevent saving or rendering.
Qualified `eligible` members still require strict complete slots, required source
evidence, explicit sender facts, a valid recipient and SMTP configuration.
Noneligible qualification members may return safe partial values and previews.

The first three values no longer need to equal source records. Edits are persisted
in draft-local `manual_overrides`; they never modify shared Creators, works,
recipient snapshots or sibling drafts. Explicit refresh updates source inputs,
preserves saved overrides, refreshes other prefills and clears sender confirmations.
Changed external context still requires refresh; a save cannot bypass that check.
Revision/lease guards prevent a late model result overwriting an edit.

`input.prefill_values` contains all four string keys, allowing empty values.
When `values` is null it is the editor starting point, not an assertion that an
email has been generated or verified. Draft `rendered` is present only when saved
values are present. Work selection uses explicitly selected works first; without
an explicit selection, it examines current-identity Library works, preferring
recorded notes and then current/reference-game relevance. No selection is mutated.
Public channel names are usable addressing suggestions, never inferred real names.

`input.work` and `slot_sources.reference`/`observation` include `evidence_kind`:
`manual_note`, `metadata` or `unavailable`. Source-only YouTube work JSON may contain
`outreach_observation` with `text`, `evidence_kind: metadata`, `source_url`, `excerpt`
and `source_field: title|description`. Metadata suggestions explicitly describe
the title/description, not full-video viewing. They do not fill verified evidence
fields or any sender fact; genuine missing evidence remains a sending blocker.

Editing firstName preserves all sender flags; channelName clears following;
reference clears enjoyed and liked; observation clears liked. Existing complete
facts retain their timestamp and receive a new fingerprint; an initial `{}` stays
`{}`. A partial draft is never facts-valid, even when unchanged flags remain true.

Migration `20260913_0023` adds `manual_overrides` on top of the deployed 0022 schema.
Old nonnull values are copied conservatively because old rows do not identify
manual edits; existing values/source/history are preserved. Maintenance is supported.
After backup and migration, use the no-network backfill command first in dry-run:

```sh
python -m app.outreach.prefill_backfill
python -m app.outreach.prefill_backfill --apply
```

It adds missing source-only suggestions to already analyzed current-identity
YouTube works, using the matching successful publication checkpoint description
where present, otherwise retained work titles. It is idempotent and does not call
providers/models, reanalyze Profiles, modify human notes or rewrite sent snapshots.
Old drafts deliberately retain their captured inputs until explicitly refreshed.
Release this contract together with the internal.11 desktop decoder/editor.

## Original P6 implementation record (September 8)

The historical behavior below is superseded by the September 13 update above.

Local implementation on the internal-Demo backend. No deployment or live provider,
model or SMTP calls in acceptance. **A draft is never send-ready in this unit.**
P7 qualification/preview/final sending and P9 reply/follow-up remain separate work.

## Templates

- `GET /api/v2/outreach/template-versions?game_id=UUID`: registered versions plus
  a read-only `builtin` descriptor; opening the list never registers a template.
- `POST /api/v2/outreach/template-versions/canonical` with `{game_id}` and
  `Idempotency-Key`: explicitly bind the original LIMINAL template. A manually
  created Game without Steam identity is allowed; a nonempty Steam ID must be
  `4952700`. No identity/name guessing and no Game writes.
- `POST /api/v2/outreach/template-versions` with `request_id`, `game_id`, `name`,
  `subject` and five `fixed_fragments`: save an immutable user-authored version.
  A durable request UUID prevents duplicate versions even with a different header.
- `GET /api/v2/outreach/template-versions/{version_id}` returns immutable content.

Canonical source: document `Ieqid5pULoUSqMxOtKTc156xnLe`, revision 69. Exact content
is in `backend/app/outreach/resources/liminal-revision-69.json`.
Raw SHA256 `6c3205c37e4d1dcdff8ee5bc8061834433e81c4cea4c40e015f4928b8dde9fcd`;
fixed SHA256 `0aaf8eef8f697b8a79307820380960c1efa492d68583b47648b01a81ab1e9b93`.
Subject, twenty paragraphs, bold, Steam link and Toki signature are preserved.
Safe formatting/link HTML only; values are escaped, fixed content is hash-checked.
The renderer does not append tracking or Yes/No buttons. Legacy outreach is unchanged.

## Composition and repair

`POST /api/v2/activities/{activity_id}/compositions` takes
`{request_id,recipient_batch_id,template_version_id}` and `Idempotency-Key`.
It preserves every member and original order of the immutable recipient batch.
It separately captures current effective Game, selected Creator/contact/work,
name confirmation, template hash and public SMTP sender identity. It never rewrites
Activity discovery context or RecipientSnapshots. Template and batch must belong
to the correct game/Activity. Read with:

- `GET /api/v2/activities/{activity_id}/compositions?limit=50&offset=0`
- `GET /api/v2/outreach/compositions/{composition_id}`

Each draft returns `revision`, `context_token`, `source_changed`, `input`, four
`slot_sources`, `missing_fields`, individual status/error, `values`, `rendered`,
`sender_facts`, `sender_facts_valid`, and always `send_ready:false`.

The context token describes **current** relevant source inputs; `input` remains
the frozen drafting input until explicit refresh. Changed input requires refresh,
not silently publishing different information under the old draft revision.
Missing email stays visible but does not block generation. Missing confirmed public
name, channel name, referenced work or recorded excerpt + verification notes + URL
keeps the member in `needs_repair`. AI fit scores, game relation and sender viewing
are not invented as a prerequisite for drafting or inferred from metadata.

`PATCH /api/v2/outreach/drafts/{id}` takes `{expected_revision,context_token,values}`.
Values contain exactly `firstName`, `channelName`, `reference`, `observation`.
The first three must equal their selected sources; observation is filled plain
text including its final period. A manual observation still needs recorded evidence.

`POST .../drafts/{id}/refresh` takes `{expected_revision,context_token}`. Repair source
data through existing Library/selection APIs first. **Refresh clears old values and
sender confirmations** and may enqueue fresh generation; show this in the UI before
the user acts. Original recipient membership and discovery context remain unchanged.

## Generation and recovery

One Celery task per ready member, existing worker pool. A dedicated adapter uses
DeepSeek V4 Flash with 2048 output tokens and structured four-field validation.
It sends only bound names/reference and recorded observation text; no selected email,
SMTP sender, source URLs, credential or full email body. Prompts treat source text
as untrusted. The server, not the model, supplies source references.

Claims commit before network I/O. A revision + lease prevents duplicate dispatch
from repeating completed/running attempts and prevents late results replacing human
edits. Individual failures preserve other members' successful output. Expired workers
appear as `failed / draft_outcome_unknown` without automatic paid retry.
`POST .../drafts/{id}/retry` with revision/context explicitly retries a failed member.
Broker failure after composition commit returns 503; replay the same composition
request/header to dispatch its existing pending drafts, not create another batch.
If refresh/retry returns queue failure, read the current draft before another action;
its database revision has already changed. No provider error secrets are returned.

## Sender facts

`POST /api/v2/outreach/compositions/{id}/sender-facts` takes:

```json
{"members":[{"draft_id":"UUID","expected_revision":1,"context_token":"64hex"}],
 "following":true,"enjoyed":true,"liked":true}
```

These are explicit human attestations to the actual template statements, including
enjoying the referenced video, never inferred from titles, generation or preview.
Only selected completed drafts are affected. Confirmation binds draft revision,
values, source input and SMTP public identity. Editing relevant inputs/values/sender
invalidates it. Without an SMTP sender it may be recorded, but is not valid for sending.
False facts can be recorded; all three must be true for `sender_facts_valid`.
That validity **does not** establish P7 sendability or send mail.

## Migration and verification

Migration `20260908_0016` adds three tables atop 0015, without rewriting existing
Profiles, recipient records or settings. Populated downgrade refuses destructive
loss; maintenance-window migrations are the supported deployment model.
Focused checks cover canonical fidelity, registration, immutable membership,
source/revision conflicts, manual editing, explicit facts, HTTP → queue → real worker
→ strict model HTTP fixture → durable read, individual retry, broker replay, expired
leases, late-result protection and current-version migration. Full-suite and bounded
independent-review results are recorded at unit acceptance, not implied by this doc.

### Accepted local verification, 2026-09-08

Final realRedis full suite: **2236 passed, 3 skipped, 0 failed**, 208.52 seconds.
52 new tests cover this unit. One existing Starlette/AnyIO deprecation warning.
The three skips are the previously approved concurrent-old-writer/rolling-migration
cases in `test_migrations.py`, not P6 omissions.

One read-only integrated independent review found one blocker: legitimate video
title square brackets were mistaken for placeholders. A failing schema/render test,
minimal placeholder-specific fix and real HTTP bound-title regression resolve it.
Canonical placeholders remain rejected; normal `[Full Playthrough]` is preserved.
The minor prompt prefix mismatch was also corrected. No second broad review or
scope expansion. Final full run includes both fixes and the new regressions.
