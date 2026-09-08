# F8 / P6 — locked templates and source-bound drafts

Approved continuation from main after F7 `8236f6abd76e1394c39ddaf5a82a9c4a6fad5e0f`; no new design-approval cycle or worktree. Use the existing React pattern, TDD and one integrated independent review. User explicitly selected GPT-6 Astra / Medium for this task and new workers. Desktop source only; no backend/contract/native/Keychain/package/push changes.

Contract: immutable backend A `5ffd7c47` (resolve full hash in repository), `docs/backend-v2-outreach-drafts.md`, schemas/routes/repositories `outreach_drafts.py`, `draft_inputs.py`, `locked_templates.py`, template repository and worker. Root read these completely; relevant files are unchanged in accepted B `ece2e9d`. Fixture62611/actual0017 is exclusively handed to root for F8/P7;65164 remains F7-only. No C, Steam or YouTube binding interfaces on62611. All fixture model/SMTP identities are synthetic; this unit never calls SMTP. No existing successful history is edited for test setup.

## Task path and information hierarchy

Current prepared N people → choose an immutable game-bound template → explicitly create N drafts → review one email with its four bound values → repair relevant source or retry one failed member → explicitly attest sender facts for a chosen completed subset. Return to people/discovery/history without losing the current local edit. No new top-level business page and no compulsory per-person approval wizard.

| State | Main focus / action | Supporting content / disclosure |
|---|---|---|
| Template choice | Full locked email / Create N drafts | Compact version selector; game binding and model-use consequence visible before creation |
| No matching version | Save new version or explicitly register canonical | Builtin preview is read-only; listing never registers; other Steam games cannot use LIMINAL original |
| New version | Subject and fixed text around four named slots / Save new version | Existing version never overwritten; formatting/source metadata on demand |
| Generating | Stable N roster and current mail area / continue inspecting | Per-person queued/running/failed/needs-repair; no fake percentage or forced selection/scroll |
| Draft editing | Email and four fields / Save changes | First three remain bound to recorded sources; source details/edit entry beside each field |
| Source changed | Existing mail plus changed-state / explicit Refresh sources | Warn that refresh clears values and sender confirmations; keep old draft until action confirmed |
| Partial failure | Affected person / explicit Retry generation | Other successes remain; unknown model outcome warns about possible repeated model charge |
| Sender facts | Explicit chosen completed people / Save confirmations | Three real human attestations, never inferred from AI, preview or public-name confirmation |
| History / return | Existing composition and immutable original people | GET-only open; batch membership/order and Activity source remain untouched |
| Unknown write / credential repair | Frozen intent / read current or same safe creation retry | Never rebase revision writes or replay into replacement credentials automatically |

Default content is the selected mail and compact roster. Template metadata, hashes, recorded excerpts, verification notes and historical snapshots use named disclosures. Four slot accents map fields to preview; no explanatory card stacks. Global navigation remains stable. Keyboard, narrow widths and reduced-motion keep the task usable. Drafts are always `send_ready:false`; no Send button or eligibility calculation in P6.

## Implementation boundaries

### Task1 — new typed API / production adapters (worker)

Own new `shared/drafts.ts`, `main/drafts-client.ts`, `drafts-validation.ts`, `drafts-transport.ts`, `tests/drafts-fixtures.ts`, `drafts-client.test.ts`, `drafts-transport.test.ts`. Root owns existing bridge/application/gateway/preload/mocks.

Export `SlotValues`, `TemplateSource`, `TemplateContent`, `TemplateVersion`, `BuiltinTemplate`, `TemplateCatalog`, `TemplateVersionCreate`, `CompositionCreate`, `DraftRevision`, `DraftEdit`, `FactMember`, `SenderFacts`, `DraftView`, `CompositionView`, `CompositionPage`, `DraftsAPI`. Preserve snake_case response fields and camelCase four values. `input`, `slot_sources`, `sender_facts` are bounded JSON objects with known runtime structure validated; rendered is null or subject/html/text/fixed_hash. Every draft/composition remains send_ready false, all N members retained in order.

Methods return `Promise<Result<T>>`:

```
templates({gameId}):TemplateCatalog; template(id):TemplateVersion
registerCanonical({gameId,idempotencyKey}):TemplateVersion
createTemplate({data:TemplateVersionCreate,idempotencyKey}):TemplateVersion
compositions({activityId,offset?,limit?}):CompositionPage; composition(id):CompositionView
createComposition({activityId,data:CompositionCreate,idempotencyKey}):CompositionView
edit({id,data:DraftEdit}):DraftView
refresh({id,data:DraftRevision}):DraftView; retry({id,data:DraftRevision}):DraftView
senderFacts({compositionId,data:SenderFacts}):CompositionView
```

Only canonical/template/composition creation uses Idempotency-Key; only template/composition creation has durable request_id. Validate exact routes/fields before credentials, UUIDs/token/revisions, five safe fixed fragments, source-bound four values, member uniqueness/count, scoped responses and known booleans/statuses. Keep literal URL/body tests, bounded responses, omit cookies/reject redirects and sanitize errors. `draft_queue_unavailable` can follow a committed creation or revision update; preserve its code and treat as an unresolved committed outcome, not an ordinary safe fresh retry. No network in this task.

### Task2 — frozen operation hook (worker)

Own new `components/match/draftMutation.ts`, `useDraftOperation.ts`, `tests/draft-operation.test.tsx`. Command union: registerCanonical/createTemplate/createComposition/edit/refresh/retry/senderFacts, same API inputs minus generated creation keys; createTemplate/createComposition commands omit request_id and hook creates it. Export frozen attempt, typed receipt, hook with idle/running/uncertain states, execute/retry/credentialsChanged and conservative readback helpers. Root will wire safe recovery UI.

Clone/freeze exact input, scope, expected revision/context and key. Prevent duplicate submit and late cross-credential results; no automatic retry. Persistent creations retain body/request UUID for replay; canonical retry limited to24hours unless an exact canonical game/hash record proves it. Revision operations have no idempotency header: after queue/network uncertainty require readback before any new current-revision action; never silently replay with a newer revision. A matching edit or facts receipt needs exact observed versions/effects, not UUID-only proof. Unknown refresh/retry may remain unresolved if available state cannot prove the submitted effect; safe explicit read/review instead of invented success. Tests first fail then pass; no HTTP/commit.

### Task3 — compact template choice / new immutable version (worker)

Own new `components/match/TemplatePicker.tsx`, `templatePicker.css`, `templateText.ts`, `tests/template-picker.test.tsx`. Parent supplies catalog/current game, loading/errors, selected version and mutation callbacks; component doesn't own business writes. Builtin is opt-in registration, full fixed original readable, current versions immutable, custom version explicitly saved against game. New-version form exposes ordinary subject/body editing with four unmistakable ordered placeholders; converts only new user-authored text to safe five HTML fragments, never round-trips/reformats canonical. Advanced HTML optional only if needed, not forced. A rendered email uses existing sandboxed previewDocument primitive; no script, network, business IPC, appended CTA or fabricated signature. Preserve local edits across hidden detours/errors. Named provenance disclosure, clear button labels, minimal helper prose.

### Task4 — root composition workspace and integration

Wire11 narrow main/preload methods and credential generation; add typed fixtures without mutating older behavior. Build current composition session with bounded read/poll lifecycle, explicit business-state union, stable roster/order, history GET, no hidden-cloud side effects. Reuse current person/source repair APIs and retained Creator navigation; refresh only by explicit user confirmation. Four editable fields validate firstName/channelName/reference against frozen sources and observation as single-line filled text ending with period; display source-repair links rather than accepting invented names/work. Manual edit does not need email but still needs recorded observation evidence. Preserve dirty drafts under source/poll changes, guard navigation, local failures and uncertain writes.

Sender facts apply to explicit completed subset, independent of per-mail inspection. Display exact three attestations and version-invalidated state, never set automatically. Full preview uses server-rendered immutable fixed content; current Game/source changes mark old input stale while original batch/Activity stay unchanged. All transitions keep successful members and allow targeted repair/retry; no Send/qualification UI until next accepted unit.

## Verification

Task focused TDD; root new integrated/full suite once after implementation, typecheck/build, one bounded independent review/fix check. Actual authorized62611 API→fixture worker→strict model HTTP→durable read: own labeled Activity/batch, canonical/new version, all N including missing contact/observation, manual four-value edit, source refresh and targeted failure retry, explicit sender facts, immutable original membership/context. No real providers/models/SMTP/native. Production-renderer headless with exact source and sanitized persisted ledger only after safe fixture handoff; native remains separate. Keep original failures and actual side effects. One desktop source commit, notify main for upload, then B/P7.

## Implementation and verification record

Implemented the eleven narrow bridge/main/preload methods, strict production adapters, frozen mutation/recovery hook, immutable template choice/new-version editor, all-N composition controller, selected-mail editor, explicit sender-facts subset, read-only history and retained Activity/Creator repair detours. The backend, migrations, API contract, native package, Keychain and GitHub were not changed.

The four slot colors are consistent across the new-version controls, fixed-template preview and edit fields. Existing complete mail renders the exact server HTML in a sandbox; local unsaved values do not pretend to be saved mail. Untouched queued fields do not show validation paragraphs. Source-repair labels, status chips and nearby actions replace recurring instruction text. New editor layout uses container queries so its columns respond to the space remaining after navigation; new text sizes follow the root font preference. No animated progress percentage is fabricated.

Focused TDD covered adapters/wiring, safe request replay, exact readback, manual bound values, sender facts, template retention and composition navigation. Root additionally reproduced and fixed a delayed background GET overwriting an acknowledged edit, credential invalidation of old template choices, and explicit refresh clearing only the affected local edit after acknowledgement. The two integrated MatchActivity tests exercise selected people → stopped/frozen preparation → chosen template → explicit creation → manual save, plus unsaved source-repair return without a discard dialog.

One independent Astra/Medium integrated review found one P2: credential repair cleared fetched Game state and inadvertently unmounted an unsaved new-template form. A new regression first failed with the missing textbox. The fix retains the form owner using display-only Game context while disabling actions until fresh Game/catalog data return. Explicit discard still remounts by editor epoch. The reviewer performed one bounded fix check and closed the finding; no repeated full review was run.

Verification segments are deliberately separate:

- Initial full source run: typecheck passed; 1,018 of1,019 tests passed across80 files. The existing101-row SavedSet browser test timed out at5seconds under four-worker load. It was not a failing F8 assertion. A bounded isolated rerun of its complete file passed4/4 in3.36seconds; no old test was weakened or skipped.
- After the review fix:45 related tests across4 files passed, then typecheck and production build passed. The additional regression is covered by this targeted run; a second full-suite clean run is not implied.
- Final presentation-only token/font normalization: typecheck, diff check and build passed;104 modules, assets `index-3AjsQjkp.js` / `index-CUPlC0pP.css`. Build reports a532.39kB minified JS chunk warning; code splitting was not added in this unit.
- Actual production-adapter→API→worker→strict synthetic model HTTP passed on62611 after preserving the original imported-Work decoding failure and fixing two bounded frontend response decoders. All-N retention, missing-email generation, targeted failure/retry, manual editing, explicit facts, refresh invalidation and immutable originals are recorded in [the HTTP report](outreach-drafts-real-api-verification.md). No SMTP call occurred.

The first successful headless renderer run passed42 GET/0 writes with two earlier harness-readiness failures retained. Root inspected both actual screenshots and made a final attention/layout refinement: opening a draft set collapses the now-secondary history list; the new-set heading receives keyboard focus without moving focus on background updates or ordinary detour returns; the roster stacks horizontally when the actual content container is narrow. Explicit history opens now show their own loading/error state, so a failed GET has a visible local retry. Two regression assertions failed before this adjustment and passed afterward.20 related tests/3 files, typecheck, diff check and104-module build passed. Final assets are `index-BkabE4QR.js` / `index-P_y2iGTW.css`; the532.73kB minified JS size warning remains.

The final frozen-source headless rerun passed1/1 in4.5seconds (5.4seconds including runner), with **36 GET, zero writes and zero page/console/bridge/network errors**. It checks all three members and order, exact server HTML in the sandboxed iframe, dirty edits across person→people→source/Creator→return, keyboard,1320px and760px/135%-font layouts, reduced motion, and unchanged durable Activity/composition/model/SMTP data. Source SHA256 `c7046e8c357c6feb132da54aa7751c4b0469c776684331163423fabc959f0be8` and renderer-bundle SHA256 `79c4a5e77df0671ef3352239492ebc37ccad0fff57e3be8dda2307eef9f3fbc6` were equal before and after. Root viewed both final screenshots and read the physical sanitized ledger. Prior pass and failed-run evidence are preserved; details are in [the renderer report](outreach-drafts-renderer-verification.md).

This is deliberately segmented evidence: actual persisted writes were exercised by the API/worker test and mock-backed integrated UI tests; the final real-HTTP renderer check is GET-only with local unsaved edits. It does not claim a real renderer-triggered send, nor native Electron/IPC/Keychain/final-package acceptance. No package was restarted or replaced.62611 returned to root with idle controls and queue depth0. Only desktop source/tests/docs are ready for the coordinating task to integrate and upload; this task does not push.
