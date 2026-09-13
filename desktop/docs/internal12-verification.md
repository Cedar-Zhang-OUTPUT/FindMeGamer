# Internal.12 discovery budget compatibility — 2026-09-13

Scope: one runtime validation limit, preserving all internal.11 changes. No UI,
backend business logic, database or service configuration changes in this task.

## Contract and source

- Source commit `134c657`: provider `max_requests` maximum increases from 2 to 3.
- Public field: `QueryView.conditions.providers[i].max_requests`. YouTube's new
  plan may reserve three calls including videos snippet-language lookup; old 2
  remains readable. The desktop does not rewrite budgets or measured usage.
- Direct Query and embedded Activity queries share the decoder. Internal search
  directions and cursors are not new public fields.
- TDD: old decoder rejected 3; after the one-line change new 3 and old 2 pass.
  Both read paths reject >3, negative, fractional, string, null, boolean and
  non-finite values. One bounded independent review found no P1/P2 or necessary
  missing cases.
- Focused regression: 111 tests passed. Final suite: **1358 passed / 6 skipped**,
  131 files passed / 1 skipped, 78.01 seconds; typecheck and build passed. Existing
  Vite large-chunk warning is unchanged. Renderer asset hashes equal internal.11.

## Artifact

Version `0.2.0-internal.12`, macOS build `20012`, arm64 Electron 44.2.0.
Root: `desktop/artifacts/FindMeGamer-Electron-0.2.0-internal.12-arm64-Php6cL/`.

- App: `FindMeGamer-darwin-arm64/FindMeGamer.app`
- DMG: `FindMeGamer-Electron-0.2.0-internal.12-arm64.dmg`
- Size: **151241451 bytes**
- DMG SHA-256: `40ef11cb1936efb719056baaf2d030f5d4dc1c0797b0d73a1e5639242285e8f5`
- ASAR SHA-256: `353ab28c3e2dfd490402bc6550650b707bf06d37f2cc7ea861b8320a4d5a3c17`
- Icon SHA-256: `62aaacb8c699d1bd1c40f9c048559aaee0372844d8d992a32f323044035dbf91`

Ten packaged runtime files match the build byte-for-byte. Original and mounted
ASAR hashes match. Icon and bundle version were checked. Build uses the existing
local same-version Electron archive. App strict/deep ad-hoc signature and
`hdiutil verify` passed; this is not Developer ID signed or notarized.

## Native read-only acceptance

Native compatibility acceptance passed. Dedicated localhost 18744 backend fixture serves
a real-search Query with budget 3 and a synthetic legacy-2 compatibility record.
Both are in an isolated database, without worker/provider credentials; every HTTP
write is forbidden by server middleware and the native test network guard.

The test uses the real packaged main/preload/IPC path, without replacing handlers,
reads direct Query and embedded Activity data, reloads and compares values. No
additional search, provider request, send or user-data clearing is performed.
Root owns final backend deployment and GitHub publication.

- Normal `.app` final run: **1 passed, 2.7 seconds**.
- Read-only mounted DMG, new process/profile: **1 passed, 6.4 seconds**.
- Direct and nested budgets: new `3`, legacy `2`; measured real-query usage `4`
  remains `4`, and reload preserves all values. Zero HTTP writes/page errors.
- The new Query is the backend team's real-search result; the legacy-2 row is
  synthetic compatibility data. No additional live provider call by this task.
- Evidence: `desktop/output/playwright/discovery-budget12-app-final-20260913/`
  and `desktop/output/playwright/discovery-budget12-mounted-20260913/`.
- First native run timed out at 60 seconds. Failed output remains in
  `discovery-budget12-app-20260913/`; a subsequent browser-debug run passed in
  5.4 seconds, then the normal mounted/app runs above passed without runtime
  changes or timeout increases. The first timeout's root cause is not established;
  this is reported rather than represented as a passing first-launch test.
- Test mount detached after acceptance; user installation/data remain untouched.

Release limitations: internal ad-hoc signed macOS arm64 package, not notarized;
Intel Macs and production desktop credentials were not exercised. Backend search
success and deployment are independently owned by the backend/root tasks. The
desktop makes no new claim about match quality or search-result suitability.
