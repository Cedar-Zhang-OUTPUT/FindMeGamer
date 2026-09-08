# Complete Settings migration

Goal: migrate the six Settings groups into Electron without backend or contract changes. Semantic controls and truthful compact status replace instructional paragraphs.

Spec: coordinator-authorized PRD §9 at `docs/prd-review-2026-09-08.md` in the main checkout; accepted backend snapshot 0153a38. Existing Game recovery is binding. Architecture: typed preload business methods → main-process validated adapters → existing authenticated HTTP. Local preferences/update checks are separate from workspace credentials.

## Global Constraints

- Edit only desktop/. No backend changes, real provider secrets, real external email, publication, installer, S3 key UI, language UI, local business database, Creator v2 or Discovery implementation.
- Steam credentials can be stored but the accepted backend has no Steam probe implementation. Show unavailable, never fake success or infer invalidity. Twitch and Instagram have no actionable controls.
- X probe is usage access only. Neither result proves search, balance or analysis availability. Saved credentials are write-only and never returned in IPC, logs, URLs, errors or renderer snapshots.
- Shared changes get an explicit impact confirmation. SMTP save never sends. Test email requires an explicit recipient and confirmation, never automatic retries, including unknown outcomes.
- Preserve unsaved drafts across category navigation and unrelated refresh. In-flight operations block destructive connection switches/disconnect. Existing same-origin Game credential-repair path remains intact.
- Only this Mac is disconnected; no cloud deletion. All settings have keyboard access, narrow-window behavior, dark/light/system appearance, font scaling and reduced-motion support.

## Task path and states

Settings opens to Workspace for the common connection/repair entry and remembers the chosen category while running. Six stable categories: Appearance, Workspace, Services, Auto-refresh, Email, Updates. Category choice changes the main panel without discarding edits and retains category scroll position.

| State | Focus / primary action | Supporting information / disclosure |
|---|---|---|
| Unconnected | workspace address + key / Connect | local Appearance and Updates remain usable |
| Read/loading | category controls / local loading | reserve form footprint; errors stay inside their category |
| Configured | compact status rows / Edit or Replace | credentials and advanced SMTP rate revealed on request |
| Editing | current form / Save | current values retained, discard available; password never prefilled |
| Confirming | exact shared change / Confirm | one concise impact reminder; recipient shown before test mail |
| Saving/testing | local pending state | no background refresh overwrites inputs; no automatic side-effect retries |
| Finished | saved configuration / next explicit action | close replacement input, retain category and scroll |
| Failed/unknown | error + recovery action | keep nonsecret drafts; unknown mail delivery explicitly requires checking receipt |

Appearance updates immediately, restore only appearance/font defaults. Local connection details stay in a disclosure. Services use five status rows and one expanded editor at a time while retaining drafts. Auto-refresh has two numeric day controls, no off switch, plus actual applicability. SMTP shows saved sender summary, editable form, connection test, and a separate recipient/confirm send path. Updates expose a manual GitHub release link only.

## Integration interfaces

`src/shared/settings.ts` and `src/shared/preferences.ts` define the exact renderer APIs. Do not widen them to arbitrary routes. Root integrates them into bridge/preload/application.

Cloud UI export: `CloudSettings({ api, connected, section, onDraftStateChange })`, section `services|refresh|email`. It keeps all three category components mounted (hidden when inactive). `onDraftStateChange` receives `{dirty:boolean,busy:boolean,discard:()=>void}`; discard resets unsaved cloud forms only after root confirmation. Treat unresolved send/save outcome explicitly and preserve warning. Export types in cloud module. Scope CSS under `.settings-workspace`.

Local main modules: `PreferencesStore(directory)` methods read/update/restoreAppearance with Preferences return values. `UpdateChecker({installedVersion,fetcher,preferences,clock?})` with status(), check(), checkAutomatically(); preferences supports read and an internal persisted update-attempt/check metadata API of implementer's design. No Electron imports in unit-testable core.

Main adapter: `SettingsClient(request)` with SettingsAPI-named methods returning domain values (not Result wrappers), and `authenticatedSettingsRequest(fetcher, connection, request)` with strict `SettingsRequest` route/method union. Root adds gateway.settingsRequest with credential-generation fences.

## Task 1: Shared settings adapter and tests

Own new `src/main/settings-client.ts`, `src/main/settings-transport.ts`, `tests/settings-client.test.ts`, `tests/settings-transport.test.ts`. Read shared types and existing transport/game client patterns. Do not edit shared bridge/gateway/application (root owns).

TDD: fail tests for mappings, malformed/surplus-secret response projection, validation, malicious paths/service names, finite integer ranges, request body whitelist, output/error redaction, bounded JSON, redirect/cookie/timeout policy and secret-free HTTP failures before implementation.

Routes: `/api/v1/settings/connections/{steam|youtube|deepseek|google_ai|x}` GET, PUT `{secret}`, POST stored credential test; `/api/v1/settings/reanalysis` GET/PATCH both snake_case interval fields (game 1–90, creator 1–30). `/api/v1/outreach/smtp` GET/PUT full SMTP input snake_case plus optional password; `/smtp/test-connection` POST no body; `/smtp/test-email` POST `{recipient}`. SMTP port 1–65535, rate 1–60; encryption tls/starttls/none. Backend schema is authority; inspect read-only accepted snapshot schema and normalization as needed.

Failures use PublicFailure safe fixed messages, no server detail echoed; POST send transport/server/malformed-response/configuration-changed failures convey unknown delivery and are non-retryable. Do not claim failed SMTP result guarantees non-delivery. Settings outputs project only known public fields even if server returns extras. Initial SMTP password omission remains backend smtp_password_required, or validate when known configured state; don't fake password readback.

Run focused tests and typecheck insofar as concurrent root integration allows. Do not commit; report exact owned files and test evidence. No agents under this task.

## Task 2: Local preferences and software update core

Own new `src/main/preferences-store.ts`, `src/main/update-checker.ts`, `tests/preferences-store.test.ts`, `tests/update-checker.test.ts`. Shared types exact above. No edits to Electron integration or shared bridge.

TDD persistent atomic local preference writes, invalid input rejection/unknown fields, corrupt-file fallback, serialized concurrent updates, restore only appearance/font (not automatic updates). Defaults system/default/automatic true. Appearance system/light/dark; sizes small,medium,default,large,extra-large. Store contains no business records or credentials. Use node fs promises; no renderer filesystem access.

Mirror trusted existing Swift updater (`macos/Sources/FindMeGamer/Support/AppUpdateChecker.swift`, read only): HTTPS `https://44.233.174.193/updates/macos.json`, max 32768 bytes, no redirects/cookies/workspace auth, 20s timeout, schema_version 1, plain 3-part release version; release_page_url exact GitHub repo Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/version, optional v and allowed -internal.N tag only (positive N), matching core. Reject query/fragment/userinfo/ports/mismatched version/foreign repos. Full SemVer compare installed prerelease appropriately; no build metadata order. Never download/install. Release index constant https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases.

Manual checks deduplicate concurrent calls, retain last verified available release on network error; lastChecked only successful, lastAttempt set at start. Auto checks obey enabled preference and 24-hour persisted attempt cooldown (allow clock-backwards). Malformed development installed version reports development; no false 'up to date'. Test using injected fetch/clock, no real update requests. Expose constants and class APIs specified. No actual OS mutations beyond isolated tests.

Run focused tests. Do not commit. Report tests/files/concerns; no agents under this task.

## Task 3: Cloud Settings interaction and visual panels

Own new `src/renderer/components/settings/CloudSettings.tsx`, related new per-category TSX/hooks in that new directory, `src/renderer/settings-cloud.css`, `tests/settings-cloud.test.tsx`. Do not edit App/ConnectionSettings/shared types/styles.css/root settings host. Match existing CSS primitives but use compact grouped rows, native labeled controls, explicit status and one strong action per edited task; few default descriptive paragraphs.

Use exact CloudSettings interface above and window-free injected SettingsAPI. Keep drafts across hidden category changes. Per-provider operations are explicit state machines, not many independent booleans; stale read results don't overwrite drafts or newer mutations. Cloud components only fetch when connected; disconnect clears all secret/draft state to prevent cross-workspace leakage. onDraftStateChange stable enough not to create parent update loops. API mocks Result-wrapped.

Services: five provider status rows; secure replacement fields only expanded as needed; shared-impact confirmation before replacing, clear secret after submission, test saved credential only and not with an unsaved secret. Steam test unavailable (do not call); X label 'Test usage access', concise persistent 'Search & analysis not verified' regardless of probe success/failure, details may expand to distinguish balance/recent search. Twitch/Instagram unavailable text, no fake buttons.

Auto-refresh: saved both-interval pair, Games 1–90 days, Creators 1–30 days, shared confirmation, no off control. Use neutral applicability 'Steam-linked games' and 'YouTube creators' only if verified from backend; root will finalize actual schedule activity source. Keep field edits on load/refresh race. No invented next-run or progress.

Email: host, port, encryption, username, optional replacement password, from name, Reply-To, rate 1–60 (rate may disclosure). Start defaults port 587/starttls/rate10 when unconfigured. First configuration requires password. Shared confirm Save; no automatic send. Tests disabled until saved+clean. Test connection clear inline status. Send test panel explicit recipient, separate confirmation naming recipient and sender; one submission at a time. Any send result failure or thrown/rejected outcome says delivery may be unknown/check inbox; never automatic retry or generic Retry button. Username/ReplyTo/recipient labeled email fields. Unencrypted selection warns before save; preserve needed security reminder. Snapshot secrets excluded from summaries; don't print caught errors.

TDD focus: draft survives unrelated response/categoryswitch, disconnect clears secrets, failed/confirmed save behavior, no double submit/auto resend, recipient consent, service capability caveats, unavailable services, keyboard-confirm/cancel and editable field access. Accessible custom dialogs trap focus, Escape cancel only when safe, restore originating focus. Prefer new shared local confirmation component if useful. Tests need check behavior, not source strings only. No agents or commits; report owned files/evidence.

## Task 4: Root integration, appearance, navigation, end-to-end verification

Wire exact typed IPC and generation fences; main read/update preferences, startup/activation auto checks, lifecycle cleanup. Update test bridges. Build Settings host with six stable categories, compact local controls/live appearance choices, truthful updater states. System color scheme and font sizes affect entire app (not just Settings), including dialogs and Game views; reduced-motion remains honored. Preserve cloud inputs while switching category; outer nav confirms dirty discard, busy prevents exit; local connection switch uses same protections. Game repair preserves original workspace/draft. Connect/Disconnect cannot migrate or delete cloud data.

TDD integration navigation/draft/connection fences and local appearance/update UI. Read-only real HTTP settings readback and isolated fixture writes/probes after coordinator readiness; SMTP capture only, no external mail. Run npm check, all existing E2Es, new Settings E2E (720px + wide, keyboard, dark, large font, empty/loading/failure/return edits). Inspect actual packaged UI screenshots with CUA or returned E2E images. Limited independent task reviews + final unit review. Source-only separate desktop commit after tests; handoff coordinator, no push.

## Verification record

Implemented, backend and contracts unchanged. Full `npm run check`: 312 tests / 16 suites, typecheck and production build PASS. Settings real Electron E2E PASS (5.0s on final development runtime): 720px dark / extra-large text including Creator detail and Game editor; system appearance changes; category drafts and workspace lock; 5 credential save/readback boundaries; four provider success fixtures and X failure with capability caveats; interval readback and actual activity disclosure; SMTP save/test-connection/cancel yield no messages, one confirmed send yields one additional capture; fixed update endpoint intercepted in its separate test session, no Authorization/Cookie, trusted manual link captured without navigation; Creator/Game regression.

Steam probe is unsupported in accepted backend and visibly unavailable. Providers use actual ProductionConnectionProbe request shaping with HTTPX MockTransport, not real service access. SMTP uses actual SMTPGateway with socket-free capture; actual TLS handshake, deliverability, real credentials and paid access are not claimed. Fixture unit tests: 12 PASS. Core/Cloud limited independent reviews passed after correcting unknown-save reconciliation and confirmed-action focus. Final independent whole-unit review: ready, no actionable findings.

Final packaged regression: all 5 Playwright E2Es PASS (22.6s): isolated backend, Game v2, Settings, anonymous system-proxy HTTPS, and isolated desktop navigation. Creator screenshot now explicitly waits for loaded contact data, not just its optimistic header. Inspected 720px dark / extra-large Creator detail and Game editor, Appearance, Services and Email captures. Opened the fresh packaged app through native macOS UI and verified all six categories and the live Appearance panel. User demo remains unconnected; no test credential was copied into its profile.

Fresh final `npm run check`: all 312 tests / 16 suites PASS, typecheck and build PASS. A concurrent unit/Electron run previously hit the existing 5-second budget in one long cross-page authentication-recovery test (311 passed, one timeout). The unchanged flow passed alone in 1.77s; independent review found immediate mocks and awaited state transitions, not a product defect. Only that test's overall budget is now 10 seconds, retaining all assertions and per-state waits. Final full suite passed in 13.76s. No production change was made after packaged verification.

Architecture-local arm64 app packaging and `codesign --verify --deep --strict` PASS. Embedded icon bytes match desktop/build/AppIcon.icns (the package resource is named electron.icns); the optional .icon-format warning does not mean the .icns icon is missing. Previous app preserved as FindMeGamer-darwin-arm64-before-settings-20260908. No DMG, Developer ID signing, notarization, Intel or quarantined-download acceptance, install or publication is claimed.

Installed fixture: only dedicated `fmg-frontend-http` API at 18090 recreated using accepted0153a38 source. Compose order: stable integration/compose.frontend.yaml, existing /tmp/fmg-frontend-stable.bpM1DM/settings-override.yaml, desktop/e2e/fixtures/settings/compose.settings.yaml. FMG_FRONTEND_PORT=18090, FMG_FRONTEND_PRIVATE_DIR remains the coordinator .local/frontend-http directory, FMG_SETTINGS_CAPTURE_DIR=/tmp/fmg-settings-capture.Wt7mWP. Invocation `up -d --no-deps --no-build api`; no seed, migration, DB/key/Redis reset, workers or unrelated containers. Existing override was not overwritten. Captures are synthetic local .eml/log artifacts only; fixture code and environment never enter the production bundle.

## Task 5: Isolated Settings backend test bootstrap

Own new files only under desktop/e2e/fixtures/settings/. Implement and test a test-only bootstrap that runs accepted0153a38 backend create_app with ProductionConnectionProbe using strict HTTPX MockTransport and capture SMTPGateway. No backend business file edits, no prod app integration. Existing /tmp/fmg-frontend-stable.bpM1DM/repo is the only backend source allowed. Do not restart/install containers yet; report exact proposed overlay/start commands for root approval within coordinator-authorized window. No seed/reset DB/key/Redis, workers, external DNS/HTTP/SMTP, real keys, paid calls.

Read stable integration/runtime/frontend_runtime.py (serve private-key/master initialization without printing secrets), capture_smtp.py, tests/unit/integrations/test_connection_probe.py/test_x_connection_probe.py, integration/tests/test_fake_external.py capture cases. Configure synthetic provider base origins and exact method/path/query/header matching, reject all other requests without network fallback. Four paths: YouTube /youtube/v3/channels?part=id&id=UC_x5XG1OV2P6uZZ5FSM9Ttw; DeepSeek /deepseek/models; Google /google-ai/v1beta/models; X /x/2/usage/tweets?days=1. Allow precise synthetic credential values to determine success/failure; never Steam fake success. SMTP resolver only synthetic smtp.integration.invalid:465 or587 with capture factory; reuse accepted CaptureSMTPConnection no real sockets. Fixture values sender@example.com, synthetic-smtp-integration-key, recipient company@example.com. FAKE_STATE_DIR dedicated writable capture directory; capture count/eml/log can prove save/testconnection creates0mail and explicit send creates1. Test-only bootstrap/override must mount stable main/integration runtime paths correctly and preserve existing closed-loop fallback URLs/settings-override.yaml.

TDD minimal fixture tests exercise actual ProductionConnectionProbe HTTP shaping success/failure/forbiddenorigin rejection and SMTP capture 0→1 with TLS/STARTTLS application logic (not real handshake). Use existing backend venv or container test exec read-only settings fixtures; no dependency installs. Do not modify production files or root README/plan/shared UI. Self-review bounded test fixture and report .superpowers/sdd/settings-unit/task-5-report.md with RED/GREEN, exact synthetic values (safe), proposed commands/final mounts/capture paths. No commits, agents or actual container restart until root confirms report. No persistent plaintext workspace key copies; use existing /private mountedcredential bootstrapping.

## Task 6: Actual auto-refresh schedule disclosure

Own new renderer/components/settings/RefreshActivity.tsx and tests/refresh-activity.test.tsx; a minimal additive optional ProfileSummary.nextAnalysisAt property in shared/library.ts and corresponding main/library-client.ts mapping (existing next_analysis_at already validated), focused test in tests/library-client.test.ts permitted. No other files. Export RefreshActivity({api:Pick<DesktopBridge,'library'>,connected:boolean}). A collapsed details 'Refresh activity' fetches existing v1 library.list kinds games/creators only on expansion, 100 per kind. These v1 routes explicitly filter Steam-linked games / YouTube creators in accepted repository profiles.py:43,66,167–182; preserve schema/backend unchanged. Aggregate known last analysis max(updatedAt), next scheduled min(nextAnalysisAt) with actual ISO dates and counts; missing schedule not invented, 'No scheduled refresh' for loaded records. If cursor exists show 'First N records' and explicit 'Load more games/creators' buttons, no misleading globaltotal/next ifcoveragepartial. Each category loading/failure independent and readonlyretry, preserve successfulpartialdata onfailure, noauto polling or unboundedpagination; disconnect discards snapshots and stale promises. Graceful unknown missing optional field displaysunavailable notfake. Render compact rows/dl underdetails, not paragraphwall. Main root places belowCloud refreshform, no CloudSettings file edits. TDD delayed/disconnect/loadmore/failure and optionalfieldmapping; report .superpowers/sdd/settings-unit/task-6-report.md, noagents/commits. Do not broaden toCreatorv2pages/backgroundscheduler controls.
