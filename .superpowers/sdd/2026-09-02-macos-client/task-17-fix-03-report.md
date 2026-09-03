# Task 17 Fix Round 3 Report

## Scope and baseline

- Fixed base: `09246defb74c1ade450e3aca647625771de6c90e`.
- `HEAD` matched the fixed base and the worktree was clean before the first edit.
- Changes are limited to `AppSession.swift`, `AppSessionTests.swift`, and this report. Root and
  destination policy, coordinator, feature views/models, APIService, OpenAPI/generated code,
  Package.swift, scripts, backend, deployment, and Task 16 surfaces remain unchanged.

## TDD evidence

The lifecycle regression was added before production code.

- The test first completes a real saved-key validation, drives the fake connectivity offline,
  invokes the blank-key `retryAccess` path, and holds the second validation with the existing
  `ValidationGate` infrastructure.
- It proves `.offline -> .checking -> .offline` retains the exact prior `workspaceSession`, resolves
  to Workspace throughout, and keeps writes disabled. It also checks the saved key remains and no
  deletion occurs. Gate synchronization uses no wall-clock sleep.
- RED command:
  `swift test --package-path macos --filter 'AppSessionTests.retainedWorkspaceSurvivesHeldRetryTransportFailure'`.
  It exited 1 with two behavioral issues after the transport failure: `workspaceSession` was nil
  instead of the validated session and the root surface was Access instead of Workspace.
- After the minimal production change, the new regression passed 1/1. Focused AppSession and
  AppDestination runs passed 28 tests / 2 suites twice consecutively.

## Fix

- The ordinary transport-error branch of saved-key restore/Retry no longer clears
  `workspaceSession`. A previously validated workspace therefore remains the owner when Retry
  returns Offline, preserving the existing coordinator, poller, sheets, navigation, selections,
  and drafts.
- Initial restore still begins with a nil validated session, so a transient initial failure cannot
  invent or expose Workspace. Successful Retry can replace the validated session as before.
  `workspace_key_invalid`, disconnect, missing-key, and configuration failures retain their
  authoritative clearing behavior.

## Verification

- Focused AppSession/AppDestination: 28 tests / 2 suites passed twice consecutively.
- Related Task 17, Composer, Profile, Outreach, and Match regressions: 86 tests / 9 suites passed.
- Full `swift test --package-path macos`: final consecutive runs passed 184 tests / 20 suites twice.
- `./script/sync_openapi.sh`: exit 0; 42 operations; generated files already up to date with no
  tracked drift.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
- `xcrun swift-format lint --strict` over both touched Swift files: exit 0.
- `git diff --check`, exact scope, manifest/dependency, credential-pattern, CJK, and tracked
  artifact checks: passed.
- Safe staged launch used
  `SERVICE_BASE_URL=http://127.0.0.1:9 ./script/build_and_run.sh --verify`. The exact staged app
  launched as PID `39233`, bundle `com.findmegamer.desktop`, minimum macOS `14.0`, configured URL
  `http://127.0.0.1:9`, and an arm64 Mach-O. PID `39233` was terminated; `kill -0` failed afterward
  and no `FindMeGamer` process remained.

The commit subject is exactly `fix: retain workspace after retry failure`. The immutable commit
hash is supplied in the post-commit handoff because embedding a commit's own hash in its content
would change that hash.

## Strictly nonblocking observations

- OpenAPI generation continues to emit the repository's established nullable-schema and generated
  unused-import diagnostics. The approved generated-target-local exception is unchanged, and the
  strict application build passes.
- During repeated full-suite pressure, two untouched bounded-yield test gates each timed out once:
  `JobPollerTests.multipageSyncIsAtomicOrderedDeduplicatedAndCommitsOpaqueCursor` and
  `OutreachComposerModelTests.loadFailuresAndLateContextCannotReplaceCurrentContext`. Each passed
  20/20 in isolation, and the final full suite passed twice consecutively. Neither source nor test
  is in this fix's allowed scope.
