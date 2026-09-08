# Shared collection switches implementation plan

Status: source implementation, component/contract checks, synthetic real HTTP verification and one independent final review complete. Final-source packaged/visual acceptance remains an explicit open gate; this is not a release or full runtime acceptance.

> For agentic workers: use subagent-driven-development and TDD. Coordinator has authorized the bounded design and one final integrated independent review; one desktop-only source commit, no per-worker commits or repeated design approval.

Goal: shared channel controls in Settings and honest Match pause/continue behavior without automatic collection.
Architecture: extend the existing strict Settings business API and main-only transport; isolate a Collection settings panel; Match combines current shared policy with retained query source outcomes. The server remains authoritative. No new dependencies.
Tech stack: existing Electron / React / TypeScript, Vitest and Playwright.
Spec: accepted backend `b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857`, `docs/backend-v2-collection-switches.md` and `backend/openapi.json` at that commit in the main repository. Frontend baseline `149bc69459ebc38c91e133189bf74cf45d7d551c`.

## Global constraints

- Only `desktop/` source changes. No backend/OpenAPI/contract/macOS edits, real provider/model/SMTP calls, push, merge, DMG, Release or deployment.
- Existing18090, cad5565/0012 fixture53251 and waiting pre-final-P2 `.app` are preserved. Match149bc69 packaged acceptance remains pending; do not erase that gate. No Keychain/ACL/plaintext changes or new authorization prompts while user is away.
- Shared policy, implementation, saved credentials and availability are distinct. Configured does not mean verified access. Twitch/Instagram controls are unavailable in this release even if backend policy was enabled elsewhere; never pretend implemented.
- Disabling pauses after the in-flight bounded acquisition finishes; already saved data stays. Enabling only saves the policy; no auto-continue, auto-evaluate, replay, or backfill.
- A selected disabled platform must not block another selected available platform. Unknown/read failures retain existing successful results and expose an explicit retry.
- New independent b2b15f4/0014 fixture comes from coordinator. Until formal handoff, strict local fixtures only; do not upgrade old environments.
- Analyze waiting DTOs may be implemented later with the full consumer; this unit adds no orphan analysis API or drawer.

## Approved task path and states

Settings → Collection → inspect each platform → toggle supported channel → confirm shared consequence → saved cloud state. Return to Match → current selected source state near results → explicit Continue when a selected source is eligible.

| State | Main focus / action | Auxiliary context / transition |
|---|---|---|
| Loading / read failed | Saved channel state / Reload | No guessed off switches; keep previously loaded values marked stale |
| Ready | Four channel rows / toggle YouTube or X | Credentials and availability distinct; unavailable platforms have a visible label |
| Confirming | Enable/disable one shared platform / Confirm | Changes apply to all coworkers; disable is after in-flight work, enable does not resume tasks |
| Saving | Local row progress | Prevent duplicate writes and connection changes; no optimistic success |
| Failed write | Outcome needs readback / Reload saved settings | No automatic repeat PUT or paid call; cancellation never rewrites cloud state |
| Discovery with one disabled source | Results and still-active source | Disabled marker does not replace retained provider status |
| No eligible source / all disabled | Paused / Collection settings | Saved candidates and budgets remain; no false exhausted/zero-success state |
| Re-enabled | Ready to continue / Continue discovery | Existing cursor remains server-owned; no dispatch until explicit click |

Default content is compact rows/status chips. Consequences appear in confirmation or the relevant paused state, not as repeated instructional paragraphs. Category/tab/keyboard context remains stable; system reduced-motion and large-text settings are retained.

## Task 1: strict collection adapter and fixtures

Files owned: `src/shared/settings.ts`, `src/main/settings-client.ts`, `src/main/settings-transport.ts`, new `tests/collection-client.test.ts`, `tests/collection-transport.test.ts`, `tests/collection-fixtures.ts`, minimal `tests/settings-fixtures.ts` methods. Do not modify root IPC/App or renderer.
Interface: export `collectionPlatforms=['youtube','x','twitch','instagram']`, `CollectionPlatform`, `CollectionPlatformState {platform,enabled,implemented,credentials_configured,availability}` with exact backend snake-case fields and availability union; `CollectionSettings {items:CollectionPlatformState[]}`. Extend SettingsAPI/SettingsClient with `collection()` and `setCollection({platform,enabled})`, Result envelope only at bridge. Existing settings transport GET collection and PUT collection/platform exact `{enabled:boolean}`, no POST or idempotency invented.

- [x] Write/run RED tests: GET/PUT exact paths/body, false preserved, arbitrary platform/path/field/method rejected, strict booleans, malformed/duplicate/missing four-platform responses rejected, unknown raw secret fields projected out, availability semantics retained, no availability-as-enabled inference.
- [x] Implement minimal strict adapter and transport. Test no credentials/cookies/redirect or arbitrary route leak, read/write failure sanitization and zero automatic repeats. `configured_unverified` is not a success probe.
- [x] Add literal complete fixture and central mock default (YT/X enabled/configured; Twitch/Instagram disabled/unimplemented). Run focused tests and typecheck once interfaces have landed. Report RED/GREEN evidence; no commit, tools/HTTP/runtime/environment operations.

## Task 2: shared Collection Settings panel

Files owned: new `src/renderer/components/settings/CollectionSettings.tsx`, `collectionSettings.css`, `tests/collection-settings.test.tsx`; modify `SettingsView.tsx` + `tests/settings-host.test.tsx` only for integration if needed. Do not modify API/main/App/Match.
Interfaces: `CollectionSettings({api:SettingsAPI,connected:boolean,active:boolean,onDraftStateChange?:(state:CloudDraftState)=>void})`. Reuse exact CloudDraftState shape from CloudSettings. SettingsView adds a shared Collection category and optional `collectionRequest?:number`; a changed positive request opens Collection unless connection.recovering (Workspace takes priority). Main root will pass the request.

- [x] Write/run RED for real component: load four literal states, missing-credentials vs disabled vs not-implemented distinct; successful configured state never says connection verified; unavailable Twitch/Instagram controls disabled.
- [x] Toggle opens focused keyboard-safe confirmation before one exact PUT; Cancel/Escape leaves cloud unchanged. Include shared coworker consequence, disabling after in-flight collection, enabling does not resume. Do not change input until confirmed response; lock during save; success uses returned all-platform state, never localStorage/business persistence.
- [x] Write/run RED for rejected/lost PUT and readback: no auto retry or fake saved state, explicit Reload saved settings reconciles current server truth, read failure retains last known rows, late reads cannot overwrite later saves, duplicate click prevented synchronously. Existing CloudSettings + collection draft/busy guards both protect connection changes/navigation. Clearing confirmation doesn't discard other shared drafts.
- [x] Preserve mounted panel across Settings category navigation, fetch on active entry and explicit reload, not on every unrelated render. If disconnected show proper connection-needed state. Keyboard category arrows/focus and compact narrow/large-text CSS; background read no focus steal. Run focused tests. No app launch/fixture controls/commit.

## Task 3: root Match policy and integration

Files: application/preload exact Settings method registration; Match policy helper/hook/tests, MatchActivity/MatchWorkspace/App, optional condition summary/controls and tests; this record and README; accepted fixture HTTP test after handoff.

- [x] TDD current policy read and source blocked_reason decoding/presentation: strict known optional blocked_reason, preserve actual status, no raw unknown values claiming availability. Current settings refresh on task activation/explicit refresh and bounded active polling; previous policy errors do not clear results.
- [x] TDD continuation eligibility: respect real result/request/scan budgets, keep per-query selection separate, any selected supported enabled configured source can continue despite another disabled source; all unavailable/disabled has a direct Settings entry, no auto POST after toggle or reads. Retained blocked markers clear only through backend query updates; re-enabled policy permits explicit continue.
- [x] Wire Collection Settings direct navigation without breaking Match drafts/Settings repair. Existing error and unknown-paid-intent guards remain binding. New Find creators starts only through an explicit button with at least one eligible selected channel; retain selected preferences and explain blocked source compactly.
- [x] Run fresh full test/typecheck/build, one bounded independent integrated review, fix verified normal-path findings with regression tests. After new fixture handoff run actual strict SettingsClient over authenticated transport GET/PUT and read-only Match assertions, restore changed shared policy, no paid calls except separately authorized fixture tests. Native packaged/visual gate remains pending while OS authorization is unavailable.
- [ ] Update executed evidence/limits and one source commit; hand off to coordinator, no push. Do not mistake static E2E listing or jsdom coverage for packaged acceptance.

## Verification checkpoint — 2026-09-08

- Final source typecheck passed; fresh full suite **631 tests / 41 files passed**, 21:14:46 local start, 19.75 seconds. Build passed, 74 renderer modules (`index-V-yl3-0t.css`, `index-CCCRYIiV.js`). These are source/component checks, not packaged or live-provider acceptance.
- Root observed RED→GREEN for policy/source eligibility and malformed blocked reasons, source status presentation, draft-preserving Collection navigation, same-origin read-auth repair, and stable background-refresh controls. Panel worker observed RED→GREEN for confirmation, failure/readback gating, late-read/save ordering, connection fences and keyboard focus. Full tests include existing Library/Creator/Game/Settings and frozen-intent regressions.
- New isolated fixture was formally handed over exclusively: `http://127.0.0.1:59414`, backend `b2b15f40e0ed0f8c7de7bf17ec190acb4c0e3857`, migration `20260908_0014`. Real `SettingsClient` + authenticated Node HTTP transport check passed **1/1**, 21:10 local: four-platform GET, explicit YouTube PUT, GET persistence, original settings restored in `finally`, credentials and other platform fields unchanged. Existing settled Match query status, results, source metadata, batches and budgets stayed identical; provider/model fixture event bytes did not increase. No Match POST, provider probe, SMTP, control change or actual provider/model service was invoked.
- One independent final integrated review inspected the complete modified and untracked desktop scope against baseline `149bc69` and accepted backend documentation/OpenAPI: **clear, no concrete P1/P2 findings**. The reviewer performed no network/GUI operations; its assessment does not replace root test evidence.

## Runtime boundary and next acceptance

The waiting old package and its isolated process remain untouched. Its `app.asar` still hashes to `def5533b90e4dbf3976f3885f5874c2551e5ce25a18de3975f7f8f174ec77ee7`; it predates the two final Match149bc69 recovery fixes and this Collection unit. The old visual runner still had no new output at the last read-only check. A native window read timed out. A fresh read-only process sample still showed `SecItemCopyMatching` → Keychain item content → `SecurityServer::ClientSession::decrypt`; startup has not been observed to clear that boundary. No new authorization prompt, Keychain ACL change, plaintext fallback, replacement of the running package, or GUI success is claimed.

The user reported the manual step handled. The coordinator allows a later explicit final-source package in an independent output path if existing authorization is actually usable. Final-source Match F4 paths, Collection GUI flow, native narrow/dark/large-text/focus/reduced-motion acceptance remain required; they are not waived by HTTP/component tests. The original Match E2E is pinned to `cad5565` / `0012` and cannot be blindly run against this new collection-dependent source: coordinate a fixture-compatible final-package acceptance separately, retaining the old unit's pending gate and environment.

No backend, OpenAPI, migration, macOS source, production setting or real provider credential changed. Later query-options (`8cf755e`), named lists, full Analyze, templates and SMTP workflow stay outside this unit.
