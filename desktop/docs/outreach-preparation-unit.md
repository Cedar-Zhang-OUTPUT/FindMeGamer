# F7 explicit people, one email and frozen preparation

> For agentic workers: use subagent-driven-development and test-driven-development. The coordinator explicitly approved this next unit, independent of the prior source commit and pending native gate. One integrated independent review and one desktop-only source commit; no per-task commits/reviews. Existing linked worktree stays in place.

Goal: take an explicit Activity human selection into a stable N-person preparation workspace, with one chosen current contact, public-name confirmation and recorded works; retain incomplete members and immutable history.
Architecture: a narrow nine-method `outreach` bridge; authoritative paged selections separate from candidate model output and named-list marks; explicit mutation intents with frozen retry bodies. A compact selection toolbar leads to an in-place person editor or batch workspace. No send/template/model-slot workflow is fabricated.
Tech: existing Electron, React, TypeScript, Vitest and opt-in production-adapter HTTP tests, no new dependencies.
Spec: coordinator F7 dispatch and immutable main `a852307d6908e671ae1998c9741f19ffe65f5048:docs/backend-v2-outreach-preparation.md`, `backend/openapi.json`, `backend/app/schemas/activity_outreach.py`. Read with `git -C /Users/cedar/Documents/ChatGPT/FindMeGamer show HASH:path`. F7 started on `af3ad07db6228d5d76fb8653657fbd6319724cab`; its source-commit parent is the separately accepted hidden-Settings supplement `aec17c3215bc24d5cee7cc05e669fe89abb0747f`.

## Global constraints

- Only desktop source/tests/docs. No backend/OpenAPI/macOS/package/Keychain/ACL/plaintext-fallback edits, no real providers/models/SMTP, no push/merge/release/deploy.
- API paths are scoped to `/api/v2/activities/{activity_id}`. Selections, not candidate `selected=false`, are human authority. Activity+platform+account dedup; additions explicit, late arrivals unselected, sorting read-only. Opening history or named sets never mutates selections.
- Filter changes may remove only the previously visible explicit selection projection that is no longer in the server-filtered set. Obtain full relevant membership before mutation; never treat a failed read or an unloaded page as exclusion. Never cancel other Activity lists. Show the exact removed count and retain state on failure.
- Single contact UUID/null, no first-email default or all-address send. Display purpose/source/status; invalid/inactive/historical choices not selectable. Public name and known work references require explicit action; no sender-watched or gameplay inference.
- All POSTs freeze path/body/key. Batch freezes request_id plus explicit ordered1..600 selection IDs/revisions/context tokens. Existing stop must succeed before freezing; pending/unknown stop cannot proceed. N includes missing email/evidence. `send_ready=false`, `send_ready_count=0`, original snapshot never rewritten.
- Stale revision/context errors retain edits and expose explicit read-back/review; never silently rebase a mutation. Same-key/body retry for unresolved writes, durable batch request ID survives HTTP replay-window expiration. No automatic retry; credentials replacement fences late responses and disables old replay.
- English, compact controls and factual state chips; task focus through interaction, not explanatory card stacks. Errors/consequences and missing requirements remain visible when relevant. No auto focus/scroll takeover or collapse of active edits. Keyboard and reduce-motion supported through current primitives.
- One root full regression/build and one bounded independent review. Only coordinator-authorized isolated65164/a852307/0015 HTTP calls; credentials remain Node-only, controls untouched. Native/headless gates explicitly separate and currently pending. Do not launch/install browsers or replace the old waiting app.

## Task path, hierarchy and transitions

Candidates → explicit single/loaded selection → compact Selected N entry → one person's email/name/works → Prepare N → stop discovery → frozen N-person workspace → repair a person or inspect original snapshot → return to candidates/history. Data remains visible while reads refresh; no compulsory field-by-field wizard.

| State | Main focus / action | Auxiliary and transition |
|---|---|---|
| Candidates | Rows / Select creator or Select loaded | Count + Selected N; named-list marking remains separately named |
| Selected people | Compact person list / Prepare N | Selection removal and per-person editing, current search retained |
| Editing person | Email radio options, public name, chosen works / Save changes | Creator details, source details and evaluation context on demand; Cancel preserves server state |
| Stopping/freezing | Stable N preview / local progress | Previous query and membership retained; unresolved outcome offers same-intent retry |
| Batch | Same ordered N people / choose person to repair | Missing-field chips; original snapshot/context/history under details; no Send button |
| Conflict/read failure | Relevant row/form / Reload current | Draft remains until explicit replacement; successful context retained but stale membership actions disabled |
| Unknown mutation | Submitted intent / Retry or confirm matching saved state | Leaving/replacing intent guarded; credential changes cannot replay against another workspace |
| Return | Prior query/filter/order/capacity | No mutation on restoration; completed batch summary stays available |

Default display is people, chosen address/status and one primary action. Sources, raw recorded evidence, saved context and history are opt-in details. Missing contact/name/evidence appear next to the person, not piled at page top. Changing filters is an explicit action; background reads cannot cancel selections. One shared editor is reused before and after freeze, current preparation updates do not replace immutable snapshot.

## Task 1: strict outreach DTO, client and transport

Ownership: create `src/shared/outreach.ts`, `src/main/outreach-client.ts`, `outreach-validation.ts`, `outreach-transport.ts`; create `tests/outreach-fixtures.ts`, `outreach-client.test.ts`, `outreach-transport.test.ts`. No existing bridge/application/gateway/preload/renderer files. Read exact schemas and existing Creator/Match decoders; reuse their exported decoders without editing peers' files.

Interface: export contract types `PreparationContact`, `PreparationWork` (WorkDetail + relation/evidence_status), `SelectionIdentity`, `Preparation`, `SelectionCreate`, `SelectionRevision`, `SelectionCancelChoice`, `SelectionBulkChange`, `SelectionBulkResult`, `SelectionUpdate`, `RecipientChoice`, `RecipientBatchCreate`, `FrozenRecipient`, `RecipientBatchSummary`, `RecipientBatchDetail`, `SelectionPage`, `RecipientBatchPage` with snake_case schema fields. `OutreachAPI` methods all return `Promise<Result<T>>`:

```ts
selections({activityId,includeCancelled?,offset?,limit?}): SelectionPage
selection({activityId,id}): Preparation
add({activityId,data:SelectionCreate,idempotencyKey}): Preparation
bulk({activityId,data:SelectionBulkChange,idempotencyKey}): SelectionBulkResult
update({activityId,id,data:SelectionUpdate,idempotencyKey}): Preparation
cancel({activityId,id,data:SelectionRevision,idempotencyKey}): Preparation
batches({activityId,offset?,limit?}): RecipientBatchPage
batch({activityId,id}): RecipientBatchDetail
freeze({activityId,data:RecipientBatchCreate,idempotencyKey}): RecipientBatchDetail
```

`OutreachClient` constructor `(request: (input:OutreachRequest)=>Promise<unknown>)`; unwrapped same methods. Export `OutreachRequest`, `validateOutreachRequest`, `outreachOutcomeUnknown` via client/transport; `authenticatedOutreachRequest(fetcher,connection,input)`. Type-safe routes and exact fields, no generic renderer HTTP. Export `decodePreparation` and `decodeRecipientBatch` if useful for cross-scope receipt validation.

- [x] TDD exact9routes/query names/listlimit1..200/offset>=0, strict UUIDs/token64hex/revision>=0, input known keys, bulk1..600 unique additions/removals and atomic nonempty operation, work_ids<=100, freeze1..600 unique ordered IDs. Preserve omitted update fields vs explicit null/false; never mutate/normalize frozen POST body. Assert literal emitted URL/header/body at real adapter boundary and invalid routes before fetch.
- [x] TDD complete strict response structures and scope IDs; current/snapshot identities, counts/order, invariant false/0; nullable contact, all N including incomplete, source fields bounded JSON; reuse Creator Work and Evaluation decoders. Reject mismatching activity/selection/batch/request IDs. Frozen snapshots can intentionally have empty contact_options while selected_contact exists.
- [x] TDD bounded response/cookiesomit/redirecterror/timeout; no raw errors/secrets. Actual safe backend error codes include selection_revision_conflict/preparation_context_changed/recipient_batch_request_conflict (read repository for exact others). Lost POST/5xx/malformed-success is `outreach_outcome_unknown`; known deterministic rejection stays editable; GET retryable. No network/runtime. Run focused new+related tests/typecheck, self-review, report RED/GREEN. No commit/subagents.

## Task 2: frozen mutation operation hook

Ownership: create `renderer/components/match/useOutreachOperation.ts`, `outreachMutation.ts`, `tests/outreach-operation.test.tsx`. Depends on Task1 type exports, no bridge/UI or shared fixture edits. You may wait for type file; do not duplicate/modify it.

Interface: `OutreachCommand` discriminated by `kind:'add'|'bulk'|'update'|'cancel'|'freeze'`, matching the API inputs except idempotencyKey; freeze command `data:{recipients:RecipientChoice[]}` (hook assigns durable request_id). `useOutreachOperation(api:OutreachAPI)` exposes `state` (idle/running/uncertain with error, immutable attempt), `execute(command)`, `retry()`, `confirmBatch(batch):boolean`, `confirmSelections(preparations:Preparation[]):boolean`, `credentialsChanged()`, `busy`, `locked`, `retryAllowed`. Receipt union `{kind,data}` matching command. Frozen attempt exposes original command, actual input, startedAt, connectionChanged. Parent calls stop first; this hook must never call Match/stop automatically.

- [x] RED/GREEN missing feature: double click submits once; input clones/freeze path/body/key, all command kinds route exactly once; delayed data cannot be changed by caller mutation. Known first rejection idle; uncertain lost/thrown/5xx retains attempt; retry same body/key, >24h freeze request_id retained, nonpersistent mutations no unsafe replay beyond24h. Prior uncertain retry deterministic rejection stays locked until proven resolved.
- [x] RED/GREEN reconciliation: batch exact activity/request_id/ordered members + snapshot revision/context; reject another batch. Selection reconciliation requires every requested effect observed and matching target IDs/revisions/contact/work/name fields; add uses actual requested candidate where provable, cross-query ambiguity stays unresolved. Never allow arbitrary confirmation with only a boolean. Bulk checks each requested effect; cancellation requires inactive/newrevision. No false resolution from unrelated records. Input field absent is preserved, not assumed clear.
- [x] RED/GREEN credential generation fence/unmount: no replay or late success on credential replacement; in-flight cannot confirm/discard; state exposes repair path. Focused hook tests only, no HTTP/native/commit/subagents; self-review/report precise unknown/recovery limitations.

## Task 3: compact person preparation editor

Ownership: create `renderer/components/match/PreparationEditor.tsx`, `preparationEditor.css`, `tests/preparation-editor.test.tsx`. Depends on Task1 DTO, existing `CreatorAPI` works reader and WorkDetail. No MatchActivity/session/bridge/API/centralfixture edits.

Interface: export `PreparationEditor({preparation,creators,active,busy,onSave,onOpenCreator,onOpenExternal,onRefresh,onDirtyChange})`. Types: Preparation; creators Pick<CreatorAPI,'works'>; booleans active,busy; onSave `(data:SelectionUpdate)=>Promise<boolean>`; onOpenCreator `(id,section?:'overview'|'contacts'|'works')=>void`; onOpenExternal `(url)=>void`; onRefresh `()=>void`; onDirtyChange? `(dirty:boolean)=>void`. Parent owns selection mutation/error/reload guard; editor owns draft. Export `PreparationSnapshot({preparation})` read-only concise immutable summary for details, with no edit/send controls.

- [x] TDD real component: display one explicit current email radio group including None; initial null stays null, multiple choices show purpose/source/status without paragraph instructions; invalid/inactive/historical disabled. Same email source change allows explicit reselect. Save sends contact_id only after explicit edit. Context token/revision always the observed original; no auto confirmation or auto-save.
- [x] TDD public habitual name explicit checkbox/action; missing name offers edit Creator. Works chooser reads all available current works via paged Creator works on demand (limit100; Load more); editable subset<=100, include existing missing IDs until explicitly removed. Work labels distinguish Other recorded content and metadata/recorded evidence; no inferred gameplay/sender viewing. Evaluation shown from existing preparation, explicit clear possible; no made-up model selection.
- [x] TDD draft preserved while inspect/return and failedSave; Cancel reverts local edits; new incoming context does not overwrite dirty draft. Expose changed-context warning plus explicit discard/reload action. Name/email/source provenance details only on demand. Missing fields contextual chips, no raw technical stack dump. Keyboard focus accessible controls, mobile-width CSS and reduce-motion. SuccessfulSave resets dirty using parent fresh preparation. Tests assert emitted minimal update and no initial writes; run focused/typecheck, no network/commit/subagents.

## Task 4: root integration and authoritative selection workspace

Ownership: bridge/application/gateway/preload/settings-fixtures, MatchActivity/MatchResults/SavedSetBrowser, new outreach session/projection helpers and selection/batch workspace, integration tests and opt-in HTTP spec.

- [x] TDD narrow main/gateway/preload9methods, validate before credential retrieval and generation fence. Wire authoritative paged selections including cancelled recovery separately from candidate and named-set marks.
- [x] TDD human checkbox/single/bulk explicit additions from current loaded candidates; no write on late arrivals/order/history/restore. Selected N opens roster, per-person shared editor and remove. Identity mapping uses activity/platform/account, never model selected. Stale reads freeze actionability. Max600 peroperation/batch with explicit subset of larger Activity lists, no silent drop.
- [x] TDD filter change captures only previous explicit visible projection; load server full membership using candidate query with pagination then exact bulk cancellation of excluded old projected members. Failure retains controls/selection and retry; sort alone no writes. Named saved-set restores never cancel. Draft/Creator return retains query/evidence/order/capacity.
- [x] TDD Prepare N captures ordered selected IDs+revisions/context then existing stop; only successful stop proceeds to same frozen batch request, unknown stop cannot. Late arrivals do not enter; incomplete persons remain N. Batch/history uses GET only; current repair doesn't mutate original snapshots/count/source. Unknown freeze recovery same durableID; guarded navigation and credential replacement preserve safety.
- [ ] Root integration/full tests, typecheck/build; one clean-context bounded review with fixes; actual pinned isolatedHTTP adapters add/select/emailnull/repair/freeze allN/reopen/currentvsoriginal/idempotent/latearrival. No real providers/model/SMTP. Record native/headless pending honestly; one source commit and notify coordinator for upload, no push.

## Verification record

Source verification, 2026-09-08: **924 tests / 69 files passed**, TypeScript passed, production build passed (90 renderer modules), and `git diff --check` passed before the final runtime-discovered history timing fix. The parent hidden-Settings supplement had805/58 passing; the earlier F6 source had803/57. Pre-fix renderer assets: `index-LBYjcDu5.js` and `index-ASYt7t_t.css`. After that final minimal fix, **35 related tests /5 files passed**, TypeScript/build/diff-check passed; the JavaScript asset became `index-CAHuYXLE.js`, CSS unchanged. No post-fix full-suite run is claimed.

### Completed source behavior

All four tasks above are implemented. Tests cover the nine narrow API methods, strict scope/field validation before credentials, generation fences, ordered batch invariants, one-email/null selection, captured filter projection and failed-membership safety, no automatic late-arrival selection, saved-list separation, stop-before-freeze, same-intent recovery, current repair versus immutable history, guarded Creator detours and draft retention. The existing query-renderer harness now permits the required read-only human-selection count; other outreach operations remain rejected in that separate query-only test.

The single integrated independent review found two Important issues: credential recovery could unmount a dirty person editor; contact readback could incorrectly accept a later source version under the same UUID. Regression tests first failed against the old behavior, then passed after retaining drafts with stale actions disabled and comparing the observed contact source/version as local-only readback proof. The proof never enters the HTTP body. The same reviewer's bounded fix check also found an empty-list navigation bypass; its failing UI regression now passes through the same unsaved-change guard. All three findings are closed; focused34/4, then the fresh full924/69 run include the fixes. No second broad review was performed.

### Real HTTP acceptance and persisted effects

Exclusive synthetic origin65164, immutable backend `a852307d6908e671ae1998c9741f19ffe65f5048`, actual migration0015. Node reads the private0600 fixture; credentials and email values are not printed. Controls remained byte-identical. No real model/provider/SMTP, backend/schema edits, package/native/Keychain changes or unrelated environment writes occurred.

Two earlier attempts are retained, not erased: each created one labeled Activity and one synthetic query; the second also continued that query. Neither created selections or batches because the fixture had no eligible contacts. The accepted all-nine-method flow then passed1/1 (2.1-second scenario): one separate Activity, two synthetic queries, two selections and one immutable batch;17 POST attempts including deliberate replay/conflict probes. It exercised null-contact retention, stale conflict, cross-query account deduplication retaining the original candidate ID, later arrivals excluded from captured N=2, stop receipts before freeze, incomplete membership, both HTTP-key and durable-request recovery, current edit/cancel versus unchanged original snapshots, and read-only history.

The separately authorized contact supplement passed1/1 on its first run (961ms scenario): exactly two clearly fixture-purpose manual contacts were added to the already-selected synthetic Creator and retained. Only the newly created second contact's purpose/source was changed. It verified explicit second-contact selection, changed-source status, explicit re-selection and a second ordered N=2 batch. The other selection was temporarily reactivated then cancelled again. Exact writes:7 POST+2 PATCH; all pre-existing Creator fields and contacts were unchanged. The final active person intentionally retained a changed contact source for the renderer check. Exact synthetic IDs and the complete attempt ledger are in the coordinator's ignored test report; no history was deleted.

After the renderer preflight exposed a missing public-name fixture prerequisite, the coordinator authorized one additional name-only supplement. It passed1/1 (1.1-second scenario):10 GET /1 PATCH /0 POST. The known synthetic Creator's effective and manual public name were verified empty before setting the clearly synthetic `Fixture F7 Creator`. Only that field, its backend-required false confirmation, corresponding manual-override metadata, record revision and ordinary update timestamp changed. No Activity name confirmation was fabricated. The current selection retained revision4 and changed-contact status; contacts, source fields, other profile/preparation state, both original batches and control bytes were preserved. Positive name confirmation remains an explicit subsequent UI action.

### Runtime and remaining limits

The first authorized managed-Chromium production-renderer invocation failed safely in read-only preflight because the pinned active preparation had `public_name:null`; the prior handoff had incorrectly assumed a nonempty unconfirmed public name. Actual POSTs:0. No renderer page, screenshot, keyboard, overflow or console acceptance was reached. Snapshot `/tmp/fmg-f7-source-q6ruO2` matched235 desktop files /112 production source files; its build passed. This was a fixture prerequisite failure, not a product failure or accepted HEADLESS run. No automatic rerun or fixture cleanup occurred.

After the separately authorized name-only correction, the second invocation used new exact snapshot `/tmp/fmg-f7-source-K08jw1`. It completed explicit candidate selection, no-default-email verification, stop/freeze N=2, changed-contact re-confirmation and public-name confirmation, dirty Creator inspection/return, current-save versus original-snapshot checks, keyboard interactions, reduced-motion preference, and wide1320/narrow760/135%-font overflow assertions and three screenshots. Root inspected all three images: content reflows without horizontal clipping, but they capture the scrolled editor rather than the whole overview. It failed at the final historical person's snapshot: the page showed an unexpected unsaved-changes dialog. The final console/security/exact-write-ledger/history-no-write assertions were not reached. The in-memory request ledger was not exported as a physical attachment, so its intended four-POST expectation is not reported as a verified exact runtime count. The reached path and saved current/batch results establish completed mutations, not a full HEADLESS pass.

The cause was a redundant batch GET after `openBatch` had already loaded the current record. Its transient read-busy state incorrectly triggered the generic unsaved-change guard on the next click. One deferred-GET UI regression failed against the old source, then passed after restricting that effect to genuine detour reactivation; explicit open/freeze receipts remain current. No earlier write workflow was repeated and no new broad review was added.

The separately authorized **history-only recheck passed1/1** (2.2-second scenario,3.2 seconds total) on `/tmp/fmg-f7-history-xAxu0j`. Root independently compared all production source, tests and E2E files byte-for-byte with this snapshot. It opened the exact newly created batch `a44ba829-c88b-4053-875e-7cd3d1306573`, activated the person's View action by keyboard and displayed the original snapshot without a spurious dialog. No editor/Save action was exposed. The physically saved sanitized ledger records **25 GET /0 POST /0 other methods**, exactly one batch-detail read, zero unexpected HTTP/bridge calls, zero page/console errors and no sensitive console text. No external artwork request was needed in this run. Wide1320, narrow760,135%-font and reduced-motion checks passed; root inspected all three top-of-history images. At narrow width the detail follows the roster below the viewport and remains scrollable, not clipped.

Local artifacts: `/tmp/fmg-f7-history-xAxu0j/desktop/output/playwright/outreach-renderer-producti-662f4-e-history-through-real-HTTP/`, containing `sanitized-outreach-ledger.json` and `outreach-history-{wide,narrow,large-font}.png`. These are a passing local history recheck plus the separately documented prior completed UI checks, **not a rewritten claim that the earlier complete mutation scenario passed**.

Native packaged-app, Electron IPC/preload and macOS Keychain acceptance remain pending; browser/HTTP acceptance cannot satisfy these gates. No existing app package is replaced or restarted by this source unit.

Drafts and unresolved mutation intents survive in-app detours, not process crashes. Nonpersistent selection writes stop offering same-key retry after24hours; durable batch request IDs permit later readback/replay. Cross-query add recovery may remain unresolved when available records cannot prove the original requested candidate; it never invents success. Activity selections are completely loaded up to10,000 with an explicit limit error above that; a preparation is an explicit1–600-person subset. All F7 preparations remain not send-ready; templates, model drafts, qualification and delivery are subsequent units, not simulated here.
