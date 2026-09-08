# Activity selections and outreach preparation

Internal Demo backend increment from `cad5565`; migration0012→0013. No SMTP,
worker dispatch, model/provider requests, frontend changes or deployment.

## HTTP contract

All routes require Workspace Bearer authentication. All POSTs require
`Idempotency-Key`; retry the same path, key and body after an uncertain response.
Typed requests/responses are in `backend/openapi.json`.

Paths below are relative to `/api/v2/activities/{activity_id}`.

| Method/path | Body/purpose |
| --- | --- |
| POST `/selections` | `{candidate_id}` from any query in this Activity; returns201 |
| GET `/selections` | Active list; `include_cancelled=true` includes removed members |
| POST `/selections/bulk` | Explicit `add_candidate_ids` and/or `cancel_selections:[{selection_id,expected_revision}]`; atomic, max600 each |
| GET `/selections/{selection_id}` | Current preparation with revision/context token |
| POST `/selections/{selection_id}/update` | `expected_revision`, `context_token`, plus optional fields below |
| POST `/selections/{selection_id}/cancel` | `{expected_revision}`; reversible removal, no history deletion |
| POST `/recipient-batches` | `{request_id,recipients:[{selection_id,expected_revision,context_token}]}`;1–600 explicit members,201 |
| GET `/recipient-batches` | Batch summaries; frozen counts, never implies sending |
| GET `/recipient-batches/{batch_id}` | Frozen initial snapshots plus current preparation/repair state |

Lists take `limit` default50/max200 and `offset`. Single/bulk additions deduplicate
Activity+platform+accountID, including the same account discovered by another query.
Another Activity gets its own selection. Model deep-screen selection is unrelated.
Discovery/evaluation `selected=false` remains model-pipeline output; this selection
API is the authoritative human list. Newly arriving accounts are never auto-added.
UI filtering must explicitly specify removals rather than infer them on the server.

Update fields: `contact_id` (one UUID or null to clear), `evaluation_run_id` (same
Activity and identity; null clears), `work_ids` (explicit current known works),
`confirm_public_name` (true/false). Omitted fields are preserved. Revisions and
context tokens reject stale forms with409. Validation failure is atomic even for
multi-member writes; an invalid final member cannot leave earlier additions behind.

## Preparation and recovery

Contact options include purpose, source URL/type/fields, manual overrides, identity
revision and update time. States distinguish eligible, inactive, invalid and
historical. Selection never chooses the first email or all emails automatically.
The chosen contact keeps the exact observed source version; changed email/source
information requires explicit reselection. A choice is syntactically valid and
current, not proof of mailbox ownership or delivery. Real sending has later checks.

Public-name confirmation records the exact supplied public name and account identity
after an explicit action against the observed context. It is not inherited from a
global Library confirmation. Rebinding invalidates old preparation and confirmation;
old candidate identity cannot be used to prepare a replacement account. Cancel the
obsolete selection and explicitly add a current candidate; preparation is cleared
when a stored account key is explicitly reused for a new identity generation.

Works and excerpts/verification notes come from Library. A declared Game association
or reference work name is distinguished from other related content. Metadata is
not proof of watching/playing. Evaluation includes its original Brief and current
stale/identity flags; there is no fit-score eligibility threshold.

`missing_fields` identifies email, name, evidence, work association, evaluation and
identity/game issues. Editing Library then re-reading preparation refreshes status.
`sender_watched=false` and `send_ready=false` are invariant in this unit: final
template/content validation, sender-facts confirmation, sending-account validation
and final sending confirmation are explicitly pending.

## Frozen preparation batches are not final send batches

The batch preserves **all explicitly chosen active members**, including missing
emails/evidence. Thus P4 can proceed with N people to a P6-style repair state;
the server does not silently drop people or require complete data before entry.
`freeze_ready` means an active member can enter that preparation batch, **not** that
its email is valid or it can be sent. Contact can be null in the initial snapshot.
Duplicate addresses are marked `duplicate_email` repair items, not silently merged.

`snapshot` is immutable initial preparation; `preparation` is the current version
that the user can repair through explicit updates. `source_changed` identifies a
difference from the original context. Member count and original user order remain
stable. Addresses, identity, Game, work or selection changes never rewrite history.
A fresh explicit freeze can create another batch; it does not resend anything.

Persistent `request_id` recovers the same batch beyond the24h request-key record.
Reusing it with different membership/context is409. Initial snapshots bind Activity,
account identity, chosen address/source version when present, work/evaluation state
and the frozen Activity Game/reference context. Final eligible recipients, actual
addresses, template and content must be frozen separately at later sending approval.
Current `send_ready_count=0`; all members still need final sending requirements, so
`needs_repair_count` equals total until the later qualification unit is connected.

## PRD751 traceability (original text reread2026-09-08)

Original: [FindMeGamer PRD](https://k1mai98sti.feishu.cn/docx/MOoWdOYNvoogWnxF7jYcGgGinrh).
Page images and prototype validation are design evidence, not current runtime proof.

| Original page/block and function | API/implementation | Test evidence | Status |
| --- | --- | --- | --- |
| P4 `doxcnMNjfwkPP5JxG3Mbmm0zAih`: loaded-page selection, later arrivals unselected, account dedup | selections + explicit bulk | bulk75 of100, cross-query dedup, cancellation/rollback | Backend complete; UI filtering/selection wiring later |
| P4 `doxcnRowwVCfrd4OGgYx2eY6PeL`: N selected→P6 freeze | recipient-batches explicit N | subset/order, null email preserved, idempotency | Preparation freeze complete; UI must call existing stop before transition; final send later |
| P5.1 `doxcnBWPfJCXocEvg8n9gc7dPAg`: shared editable identity/contacts/works and Activity context | existing Library + preparation references | second email/source, foreign/historical rejection, known works, rebind | Preparation complete; invitation/cooperation events later |
| P6 `doxcncrNXorGNjuNQpIxsrYNmNg`: missing business email/evidence retained | null contact snapshot + current repair state | N total/0sendable, explicit email repair without changing original | Complete for preparation; model slots later |
| P6 `doxcnruGetxmtZ3W9ZInw3g2fAd`: public habitual name, observation provenance, sender facts | explicit name confirmation, known work notes, sender false | name/source version changes and no sender assertion | Name/evidence state complete; sender-fact confirmation later |
| P7 `doxcnUNlm8NKNMZWSb7WjdJFBMc`: repair counts, final eligibility and idempotent send | current batch counts/state; no send action | incomplete/duplicate-address records retained, all send-ready false | Preparation complete; template/hash/4slots/final SMTP checks later |
| P9 `doxcnRxBosYOWLOhvxucG08oVIe`: same Activity list, new batch does not rewrite history | batch membership references + immutable snapshots | email/Game/identity/work/cancel mutation preserves snapshots | List foundation complete; replies/followup/cooperation later |
| P4 named saved subsets; P6/P7 fixed four-slot template, no newYes/No | not added by this increment | No completion claim | Subsequent explicit units, not removed |

User-confirmed changes remain English analysis/prompts, Electron frontend, internal
Demo deployment boundary, Twitch/Instagram unconnected presets, necessary Settings
and later shared collection switches. None is inferred from prototype test numbers.

## Verification

The three new PostgreSQL/API/migration test files passed31 tests. Full backend
regression with realRedis passed2125 tests in153.02s, with one existing Starlette
deprecation warning and no failures or skips. Current0012→0013 migration preserves
seeded Activity/query/evaluation data. One bounded independent read-only integrated
review found no substantiated blocker; OpenAPI contains nine typed authenticated
operations. Test environment was fmg-v2-tests;18090 and actual local/cloud stacks
were not changed by this increment. No live collection, inference or sending was
performed; these results do not claim final mail or whole-product E2E completion.
