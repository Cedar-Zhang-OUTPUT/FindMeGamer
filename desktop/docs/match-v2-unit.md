# Match v2 — independent frontend unit

Status: source implementation and verification complete; **packaged real-backend E2E and visual acceptance pending manual macOS Keychain authorization**. This is a source handoff, not full unit acceptance. Source baseline `3abf262`; accepted backend authority `cad5565` / schema migration `0012`. Only `desktop/` changes. Existing worktree and approved English / Electron visual direction retained.

## Approved task path

Activity list → new activity with an existing or newly saved Game and optional reference works → discovery conditions → server planning and discovery → retained, paginated candidates → explicit evaluation of the currently loaded candidate IDs → grouped Match Briefs → existing Creator detail/edit → return to the same results.

No platform-query syntax, forced plan approval, numerical scores, fake persisted selection, or sending. Planning output is optional context, not a new obligatory step. The first discovery action uses real Game context, not static demo results.

## States and hierarchy

| State | Focus / primary action | Retained or disclosed context |
|---|---|---|
| Activities empty / ready | New activity / open an activity | Compact activity history; server pagination |
| New activity | Game choice, activity name / create | Existing game search, optional reference choices; full Game editor only on request |
| Conditions | Platform chips, compact filters / Find creators | Named filter dialogs, keyword chips, advanced budgets; quota warning before execution |
| Planning / discovering | Live status and already found candidates / Stop when a query exists | Frozen conditions and source/usage details; prior query history |
| Paused / insufficient / failed | Retained candidates / Continue or repair | Real source states, exhausted budgets and unknown-outcome acknowledgement |
| Evaluating | Frozen run and successful results | Background discovery remains independent; no automatic evaluation of additions |
| Evaluation complete / partial / no matches | Match Brief summaries / view creator or explicitly retry failed work | Server order/groups, evidence and limitations on demand; stale and identity warnings always visible |
| Creator editing | Existing editor / Save | Shared-change, conflict, uncertain-save and credential repair protections |
| Unconfirmed POST | Frozen operation / explicit safe retry or check status | Identical key + full body, expiry and changed-workspace restrictions; no automatic POST retry |

Background reads never take focus, force scrolling, close a draft, or discard successful results. Hidden tasks stop polling. User navigation restores task context. Filters commit atomically on Apply; cancel returns to the opening values.

## Implementation / ownership

1. Strict DTOs, client validation, narrow transport and fixtures — API agent. `shared/match.ts`, `main/match-{client,transport,validation}.ts`, client/transport tests. Sixteen named business methods; Creator DTO reused.
2. Pure discovery conditions and presets — conditions agent. `renderer/components/match/DiscoveryConditions.tsx`, `discoveryConditionState.ts`, scoped CSS, tests. The distinct file stems avoid case-insensitive macOS resolution collisions. Root owns submitted snapshots and network operations.
3. Candidate and evaluation results — results agent. `MatchResults.tsx`, scoped CSS, tests. Server ordering and frozen identity preserved; no roster API invented.
4. Root integration — main gateway / application / preload registration, Match workspace orchestration, activity creation and game reuse, task-specific navigation guards, frozen mutations, tests and E2E.

All implementation uses TDD (observed red then green). Parallel work has disjoint ownership and no independent commits. The coordinator explicitly requested this minimum plan and one bounded final integrated independent review, not a renewed visual-design approval cycle or unbounded per-task reviews. Existing Library/Settings baseline: 458 tests passed before this unit; rerun during final integration.

## Recovery and boundaries

- Discovery / evaluation starts are explicit POST intents; retries freeze the original key and complete body. Server queue failures can represent persisted work. A later failed replay cannot prove the initial intent was rejected.
- Paid-work `outcome_unknown` retries require explicit acknowledgement. No automatic repeat, model call, provider request, or forced retry on opening a page.
- Read failures leave existing results visible and offer a read-only retry. Partial evaluation retains successful briefs. Editing creator data refreshes evaluation validity without changing its frozen membership.
- Settings repair retains drafts. Other-origin connection changes must not replay old intents. Expired idempotency windows require read-only reconciliation before another attempt.
- Existing `18090` remains old `0153a38/0009`, untouched. Coordinator handed over a separate fixed accepted API + worker + DB + Redis with bounded HTTP fixtures for both API and worker at `http://127.0.0.1:53251`, backend `cad55656a9a15ef183c6e0ba4ba608bd61a7a1b5`, migration `20260908_0012`. Frontend performs no real provider/model/SMTP calls and never prints workspace keys. The private fixture file is not part of this repository or bundle.

## PRD traceability (revision 751)

Local original page/menu material and screenshots supplied under `.local/prd-review-20260908/unpacked/release-v5` are the design source; accepted API is an implementation boundary, not the whole product scope. Coordinator reconfirmed the Feishu original revision 751 on 2026-09-08.

Root also read the coordinator's complete original-PRD acceptance matrix, `docs/prd-acceptance-matrix-2026-09-08.md`, on 2026-09-08. Steam / Analyze entry, named lists, five evidence filters, four server-wide sorting options, Library query expansions and Activity cooperation/follow-up remain explicit subsequent units; no current-page-only imitation is offered as the full requirement.

| Original area | This unit / implementation | Evidence and status |
|---|---|---|
| Activity entry and creation | Match activity list, server pagination, name and Game | Component/client tests passed; packaged acceptance pending |
| P1.1 Game selection | Existing Game selection and full reusable Game editor | Component tests passed, including failed lookup → save new Game → create Activity recovery; packaged acceptance pending |
| P1.2 Steam / Analyze branch | Required subsequent unit | Not implemented here |
| P2.1 Game context and references | Optional existing references and frozen source context | Component/client tests passed; packaged acceptance pending |
| P3 Match conditions | Preset languages/countries/follower bands, custom values, contact/keywords/budgets, atomic Apply/Cancel | Ten condition tests passed; packaged acceptance pending |
| P4 Continued discovery | Real plan/query status, accumulated results, stop/continue/history, explicit frozen evaluation | Component/client tests passed; packaged acceptance pending. Persisted roster selection and send action explicitly deferred to accepted roster API |
| P5.1 Creator detail / evidence | Reuse existing Creator v2 record/edit; grouped briefs and evidence disclosure | Component tests passed; packaged acceptance pending; no unearned played/watched claims |
| Outreach preparation, templates, personalization, sends and replies | Required later independent units, not available in this build | Not implemented here; not represented as working buttons |
| User-approved changes | English/Electron, existing assets, fewer instructional paragraphs, unavailable Twitch/Instagram presets | Apply throughout this unit |
| New global channel switches | Future Settings + Match capability link after backend contract accepted | Separate follow-up; this unit only selects platforms for one run |

## Acceptance

Strict contract/client tests, renderer task-state and frozen-intent tests, full existing regression/typecheck/build, then packaged Electron against coordinator-controlled HTTP fixtures. Main path plus empty, processing, partial/failure, stop/continue, paginated append, explicit evaluation membership, Creator return/edit, keyboard, narrow window and reduced-motion checks. Record exact executed results here at completion; do not call contract mocks real backend E2E. Package/runtime/signature checks and one bounded independent integrated review precede one independent source commit. No push, DMG, Release or deployment.

## Source verification / conditional handoff — 2026-09-08

- `npm run typecheck` passed. Fresh `npm test` passed **593 tests in 35 files**, 20:45:48 local time, 16.85 seconds. This includes all existing Library, Game, Creator and Settings unit/component regressions. These are not packaged or real-server acceptance results.
- `npm run build` passed with 69 renderer modules. Final source build assets: `index-mhIDuXcM.css` and `index-CrxTAS9i.js`. `git diff --check` passed.
- `npx playwright test --list` found **8 cases in 7 files**, including the two new opt-in Match cases. Listing is static validation only; **0 new Match E2E cases have run to completion**. The six older cases were not rerun on this unit's package.
- One bounded final independent integrated review found two P2 recovery bugs. Both were reproduced with failing regression tests and fixed: accepting a newly saved Game clears old lookup errors/busy state; selected-task polling preserves independent Activity/history errors and owns a separate selected-plan error. The focused 11-test regression run and the fresh 593-test full run passed. No second open-ended review cycle was initiated.
- Transport and renderer tests exercise exact route/body/key validation, response ownership/shape, lost replies and replay rejection, credential generation fences, no automatic paid requests, candidate-page preservation, explicit eligible membership, unknown-outcome acknowledgement, quiet disclosed evidence, keyboard tabs, nested editing guards and same-origin Settings repair. Actual provider timing, native focus/scroll behavior and pixel layout require the pending packaged run.

### Preserved package / authorization gate

The local `.app` at `artifacts/FindMeGamer-darwin-arm64/FindMeGamer.app` was built before the two final P2 recovery fixes. Its `app.asar` SHA-256 is `def5533b90e4dbf3976f3885f5874c2551e5ce25a18de3975f7f8f174ec77ee7`. It passed `codesign --verify --deep --strict`; embedded `electron.icns` exactly matches `build/AppIcon.icns` (SHA-256 `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`). This verifies bundle structure/signature/icon, not application behavior, and **this preserved package does not exactly represent the final source commit**.

A read-only packaged visual script launched an isolated user-data profile, but startup stalled in macOS Keychain access (`SecItemCopyMatching` / SecurityServer in a sampled worker stack). No screenshot or business-path success was obtained. The coordinator explicitly requested preserving the current package and waiting authorization state because the user is away: no repeated prompts, ACL changes, deletion of Keychain entries, plaintext fallback or fake safeStorage. Final source build output is separate and does not overwrite the waiting package. A later final-source package and its real E2E remain required after user authorization.

The new fixture's controls are unchanged at `source_fail=none`, `model_fail=none`, `hold=none`; frontend has not executed fault controls or paid Match POSTs against it. Both isolated environments remain running. The coordinator authorized a desktop-only source commit at this safe point without treating the whole Match unit as accepted.

### Resume acceptance

After manual authorization, make a final-source package without destroying the waiting bundle, then run `e2e/match.spec.ts` with `FMG_MATCH_FIXTURE_FILE` set to the private coordinator-supplied client file and `FMG_PACKAGED_EXECUTABLE` pointing at that final-source executable. Only one runner may own fixture controls. Optional `FMG_MATCH_SCREENSHOT_DIR` must be an absolute temporary directory; the test only captures after credential fields are empty and disables trace/video. The fault case resets controls in `finally`.

The two pending paths are (1) real Activity/Game/reference snapshot → server plan → paused/continued deduplicated YouTube+X discovery → explicit six-candidate evaluation → limited-confidence briefs → Creator → retained results; (2) controlled planning failure/retry → partial X failure → held in-flight X page → Stop → retained candidates → Continue. Then repeat the six existing packaged regressions with their separate authorized fixtures and inspect first-fold, narrow/dark/large-text and reduced-motion screenshots. No live external provider/model/SMTP calls are authorized by this acceptance.

Limits remain explicit: packaged real-backend compatibility and runtime layout are not yet accepted, neither are Intel/Gatekeeper/notarized distribution, VoiceOver, live provider access or email delivery. Source validation is complete; the authorization-dependent acceptance gate is open, not waived.
