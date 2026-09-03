# Task 17 Implementer Report

## Scope and baseline

- Immutable base: `cc662f010cb1480429d3b7882c8f8d74f9d77522`.
- `HEAD` matched the immutable base and the worktree was clean before the first edit.
- Changes are limited to the one allowed Core coordinator, the narrow Workspace status change,
  real authenticated root composition, the two required tests, the macOS README, and this report.
  AppSession, APIService, DTO/generated OpenAPI, existing leaf feature models and views, Package.swift,
  the build runner, backend, and deployment files are unchanged.

## TDD evidence

Both required test files were the only first edits. The first focused command:

```text
swift test --package-path macos --filter ClientVerticalSliceTests
```

exited nonzero during compilation with `cannot find 'ClientCoordinator' in scope` and
`cannot find 'ClientBatchRouting' in scope`. Running the English focused command also built the
new Core test target and produced the same expected absent-feature failure. This was a genuine
compile RED before any production Task 17 edit, not a typo, fixture failure, HTTP dependency, or
environment error.

After the minimal implementation, `ClientVerticalSliceTests` passed 2 tests / 1 suite and
`EnglishCopyTests` passed 2 tests / 1 suite. Each focused suite was repeated twice with zero
failures. The vertical slice uses the production coordinator, existing real models, and one actor
fake at the API boundary. It verifies initial Library and shared Settings reads, Analyze success
refreshing `Alpha Plays`, selective batch routing, Match Recommended/Other results, exact ordered
per-Creator preview and Send identity, one accepted send, server-loaded Campaign state, and
Connected/Offline recovery preserving a dirty credential canary without a write.

## Implementation

- `ClientCoordinator` owns exactly one Library, Analyze, Match, Outreach management, Composer,
  Settings, and Job poller instance. One structured SwiftUI task starts and stops the poller,
  overlaps initial reads with its first sync, and serially consumes the single event stream.
- One pure `ClientBatchRouting` policy always updates Analyze, refreshes Library only for affected
  Profile IDs, and refreshes Match only for affected Match task or Game IDs.
- Scene activation and offline recovery request immediate Job refreshes and refresh only the
  visible workspace. The retained model graph, Sidebar selection, four navigation paths, Settings
  drafts, Analyze input, and Composer state are not reconstructed.
- All four Sidebar destinations now compose the existing real views. Profile loading is fenced by
  exact type/ID, uses safe generic failures, and routes Favorite, manual Creator fields, and
  re-analysis through exact API identities with ambiguity-safe re-analysis keys. Composer
  acceptance and explicit Resend use the retained existing models and refresh canonical Campaign
  and selected Match data after the attempt.
- `SettingsModel.workspaceStatus` is observable and its narrow local update maps only to
  `Connected` or `Offline`. It performs no API call or unrelated state mutation.
- `macos/README.md` documents the macOS floor, native macOS 26 enhancement, sync/test/staged app
  commands, service URL handoff, in-app credential handling, offline read-only behavior, and
  unsigned local versus release-owned signed distribution.

## Verification

- Focused suites: Client 2/2 and English copy 2/2, each passed twice.
- Relevant AppSession, JobPoller, Library, Analyze, Match, Composer, Outreach, Settings, and
  presentation regressions: 134 tests / 13 suites passed.
- `./script/sync_openapi.sh`: exit 0 with no tracked drift.
- Final full `swift test --package-path macos`: 178 tests / 20 suites passed twice consecutively,
  zero failures.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0. Only the established
  generated FindMeGamerAPI target's local schema/import diagnostics were emitted.
- `xcrun swift-format lint --strict` over all five changed Swift files: exit 0.
- `git diff --check`, exact scope, manifest/dependency, credential-pattern, tracked-artifact, and
  app-owned source/test/README CJK scans: passed.
- Safe staged-app verification used
  `SERVICE_BASE_URL=http://127.0.0.1:9 ./script/build_and_run.sh --verify`. The launched app was the
  staged `dist/FindMeGamer.app`, bundle identifier `com.findmegamer.desktop`, minimum macOS `14.0`,
  and exact unreachable URL `http://127.0.0.1:9`. Exact PID `99635` was terminated; `kill -0`
  failed afterward and no residual `FindMeGamer` process remained.

The commit subject is exactly `test: verify macos client vertical slice`. The final immutable
commit hash is recorded in the post-commit handoff because embedding a commit's own hash in its
contents would change that hash.

## Strictly nonblocking observations

Clean OpenAPI generation continues to print the repository's pre-existing nullable-schema and
generated unused-import diagnostics. Task 17 does not change the generated target or its approved
target-local compiler exception, and the strict application build passes.

One pre-commit full-suite recheck reported an isolated issue in the unchanged
`OutreachManagementModelTests` suite. The immediate focused rerun passed 14/14, and the next two
complete runs each passed 178/178; it was not reproducible and no product or test code was changed
in response.
