# Task 17 Fix Round 2 Report

## Scope and baseline

- Fixed base: `6ee0888dd49b5dfb5b1326a4606c0f9c9ab2dc13`.
- `HEAD` matched the fixed base and the worktree was clean before the first edit.
- Changes are limited to `AppDestination.swift`, `AppRootView.swift`, their two focused test
  files, and this report. `AppSession.swift`, coordinator and feature models/views, APIService,
  OpenAPI/generated code, Package.swift, scripts, backend, deployment, and Task 16 surfaces remain
  unchanged.

## TDD evidence

Tests were changed before production code.

- Added deterministic held-validation lifecycle coverage using the existing `ValidationGate` and
  `SessionAPI` infrastructure. During initial saved-key restore, the tests observe `.checking`, a
  provisional non-nil service, and a nil `workspaceSession`; the root policy must still resolve to
  `.checking`.
- The held-success case resumes validation and requires `.workspace` only after the validated
  session is published. The held-invalid case resumes with `workspace_key_invalid` and requires a
  direct transition to Access, removal of the saved key, and no validated workspace exposure.
- Updated the pure root policy regression to distinguish a validated workspace from a service and
  retained the `.offline -> .checking -> .authenticated` workspace sequence for an already
  validated session.
- RED command:
  `swift test --package-path macos --filter 'AppSessionTests|AppDestinationTests'`.
  It exited 1 because production `WorkspaceRootSurface.resolve` still accepted only
  `hasService:` and had no validated-workspace signal.
- GREEN focused runs passed 27 tests in 2 suites twice consecutively.

## Fix

- `WorkspaceRootSurface.resolve` now accepts `hasValidatedWorkspace` and uses it for every
  workspace-owning state. A service by itself cannot select the authenticated root.
- `AppRootView` derives that signal from the existing non-nil `session.workspaceSession`.
  Therefore provisional initial-restore services stay on the checking surface and cannot
  construct `AuthenticatedRootView`, its coordinator, poller, or feature reads.
- A previously validated session remains non-nil during offline recovery, so `.checking` retains
  the same read-only workspace and its navigation, drafts, selections, sheets, coordinator, and
  poller. No AppSession state-machine change or parallel validation flag was added.

## Verification

- Focused AppSession/AppDestination: 27 tests / 2 suites passed twice consecutively.
- Related Task 17, Composer, Profile, Outreach, and Match regressions: 85 tests / 9 suites passed.
- Full `swift test --package-path macos`: 183 tests / 20 suites passed twice consecutively.
- `./script/sync_openapi.sh`: exit 0; 42 operations; generated files already up to date with no
  tracked drift.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
- `xcrun swift-format lint --strict` over all four touched Swift files: exit 0.
- `git diff --check`, exact scope, manifest/dependency, credential-pattern, CJK, and tracked
  artifact checks: passed.
- Safe staged launch used
  `SERVICE_BASE_URL=http://127.0.0.1:9 ./script/build_and_run.sh --verify`. The exact staged app
  launched as PID `28653`, bundle `com.findmegamer.desktop`, minimum macOS `14.0`, configured URL
  `http://127.0.0.1:9`, and an arm64 Mach-O. PID `28653` was terminated; `kill -0` failed afterward
  and no `FindMeGamer` process remained.

The commit subject is exactly `fix: gate workspace on validated session`. The immutable commit
hash is supplied in the post-commit handoff because embedding a commit's own hash in its content
would change that hash.

## Strictly nonblocking observations

OpenAPI generation continues to emit the repository's established nullable-schema and generated
unused-import diagnostics. The approved generated-target-local exception is unchanged, and the
strict application build passes.
