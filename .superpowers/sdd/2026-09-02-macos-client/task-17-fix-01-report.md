# Task 17 Fix Round 1 Report

## Scope and baseline

- Fixed base: `3a6d2febe0786f53b741fb3a18cc41670b8c0aba`.
- `HEAD` matched the fixed base and the worktree was clean before the first edit.
- Changes are limited to the nine allowed Swift files and this report. AppSession, APIService,
  OpenAPI/generated code, other feature models/views/tests, Package.swift, scripts, backend, and
  deployment remain unchanged.

## TDD evidence

Tests were changed before the corresponding production behavior.

- `AppDestinationTests` first failed three behavioral expectations: retained-service `.checking`
  resolved to `.checking` instead of `.workspace`, `.checking` incorrectly allowed writes, and the
  retry surface sequence was `[.workspace, .checking, .workspace]` instead of three retained
  workspace surfaces.
- The Composer policy regression then failed compilation because
  `OutreachComposerActionPolicy` did not exist.
- The Campaign regressions failed compilation because
  `refreshCampaignsAfterAcceptedSend()` did not exist. After correcting one test-only missing
  `return`, the rerun failed only for that absent production method.
- GREEN focused runs passed 27 tests across AppDestination, OutreachManagement,
  ClientVerticalSlice, and EnglishCopy. The combined focused set passed twice consecutively.
- An extra full-suite stress run exposed the new test gate's bounded `Task.yield()` entry polling
  as flaky under parallel suite load. The exact failing assertion was `waitUntilEntered()` before
  any product assertion. The new test gates now signal entry with checked continuations and no
  wall-clock delay; no production code changed in response, and the final full runs passed.

## Fixes

- `WorkspaceRootSurface` retains a validated service's workspace through `.checking`, while
  initial checking without a service remains on the existing progress surface.
  `WorkspaceAvailability` now enables writes only for `.authenticated`; reads and navigation stay
  available during retained checking. The root shows a small standard checking notice without
  replacing the coordinator, navigation, drafts, or Sheets.
- Profile and Composer Sheets receive the live workspace write availability. One shared pure
  Composer action policy gates both the footer action and an already-presented `Send Now` action
  on writable workspace plus the existing model eligibility. Cancel and draft editing retain
  their existing model-owned behavior and are not globally disabled by offline/checking state.
- `OutreachManagementModel.refreshCampaignsAfterAcceptedSend()` requests one authoritative fresh
  full Campaign drain. When an ordinary drain is active, the request coalesces into a required
  follow-up after either success or failure; acceptances during a follow-up request one further
  latest-state drain. Atomic paging, ordering, de-duplication, errors, and last valid state remain
  unchanged. The coordinator uses this method and still refreshes the matching selected result.

## Verification

- Focused fix suites: 27 tests / 4 suites passed twice consecutively.
- Related AppSession, Composer, Match, and Profile presentation regressions: 56 tests / 5 suites
  passed.
- `./script/sync_openapi.sh`: exit 0; 42 operations; generated files already up to date and no
  tracked drift.
- Full `swift test --package-path macos`: 181 tests / 20 suites passed twice consecutively.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
- Strict Swift format over all nine touched Swift files, `git diff --check`, exact scope,
  manifest/dependency, secret, CJK, and tracked-artifact checks: passed.
- Safe staged app verification used
  `SERVICE_BASE_URL=http://127.0.0.1:9 ./script/build_and_run.sh --verify`. It launched
  `dist/FindMeGamer.app` as exact PID `14562`, bundle `com.findmegamer.desktop`, minimum macOS
  `14.0`, configured URL `http://127.0.0.1:9`, and an arm64 Mach-O. PID `14562` was terminated;
  `kill -0` failed afterward and no residual `FindMeGamer` process remained.

The commit subject is exactly `fix: preserve client work during recovery`. The immutable commit
hash is provided in the post-commit handoff because placing a commit's own hash inside its content
would change that hash.

## Strictly nonblocking observations

OpenAPI generation continues to emit the repository's established nullable-schema and generated
unused-import diagnostics. The approved generated-target-local exception is unchanged, and the
strict application build passes.
