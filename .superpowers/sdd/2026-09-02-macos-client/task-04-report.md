# Task 4 implementation report

## Outcome

Task 4 is implemented against immutable base
`93aeb0c4b20b7573f2c3bed3a1ab74f35d1e612f` with the required subject
`feat: connect macos app to workspace`. The change is limited to Keychain
storage, connectivity observation, `AppSession` startup/access state, the
minimal Workspace Access surface, and focused tests. It does not change the
backend, either OpenAPI document, generated output, Task 3 API/domain contracts,
the build runner, package pins, product identity, or Task 5 feature/navigation
scope.

The final commit SHA and immutable base-to-HEAD review byte count/SHA-256 are
reported in the implementer handoff after the commit is created. They cannot be
embedded in a file inside that same single commit without changing the commit
and review digest that they identify.

## TDD evidence

### RED

Tests were added before production code in
`AppSessionTests.swift` and `KeychainStoreTests.swift`. Running the binding
command

```text
swift test --package-path macos --filter AppSessionTests
```

produced the expected compile-time RED: `AppSession`, `WorkspaceKeyStore`,
`ConnectivityMonitoring`, `KeychainStore`, and `ConnectivityMonitor` did not
exist. This was a genuine missing-production-type failure, not a deliberately
failing assertion or an environment failure.

### GREEN and refactor

- Final focused command: 16 `AppSessionTests`, 1 suite, 0 failures, 0.064 s.
- Focused Keychain/connectivity tests: 8 tests, 2 suites, 0 failures.
- Full command: 50 tests, 5 suites, 0 failures, 0.067 s test time.
- Strict build: `swift build --package-path macos -Xswiftc -warnings-as-errors`
  completed successfully. Existing generated-target OpenAPI diagnostics remain
  covered by the pre-existing generated-target warning exception; all Task 4
  and application sources compiled under warnings-as-errors.
- Changed Swift files pass `swift format lint --strict`; `git diff --check`
  passes.

The first GREEN iteration exposed two ordinary compiler integration mistakes
(a closure returned `Void?`, and `SecItemAdd` needed an explicit result
argument); both were corrected before any successful test claim. A test fake
was then corrected to retain its injected recorder. No production test hooks or
yield/reset helpers were introduced.

## Behavior and fake-call evidence

`AppSession` is `@MainActor @Observable`; its equatable state, safe message,
validated workspace session, and retained service are publicly read-only. Its
API factory, key store, URL provider, and connectivity monitor are injected.
The live path snapshots `FMGAPIBaseURL` from `Bundle.main` and creates the real
`OpenAPIService`, `KeychainStore`, and `ConnectivityMonitor`.

Literal fakes prove these state transitions and effects:

- no saved key -> `needsKey`, zero service creation/validation;
- valid saved key -> one validation, retained service/session,
  `authenticated`;
- only `workspace_key_invalid` -> one exact local deletion, cleared retained
  state, `needsKey`; authentication-unavailable, rate-limit, server, transport,
  and cancellation failures retain the saved key/service and become `offline`;
- candidate key -> exact untrimmed value reaches the factory, with recorded
  call order exactly `["validate", "save"]`; invalid/transient candidates are
  never persisted and a save failure never authenticates or replaces the prior
  fake-store value;
- concurrent plus repeated restore -> one validation;
- offline restore plus path false/true/true -> exactly one recovery validation
  and authenticated recovery; invalid recovery deletes once with no storm;
- connectivity loss from authenticated retains service/session while moving
  offline;
- disconnect performs one local fake-store deletion, clears retained state,
  and makes no additional API call;
- missing, empty, file, relative, and hostless URLs make zero API factories and
  show a configuration failure; exact localhost HTTP and HTTPS values are
  accepted unchanged.

## Keychain and connectivity evidence

The Security adapter tests intercept every call; no test invokes a real
`SecItem*` function. Queries assert a generic-password identity with exact
service `com.findmegamer.desktop`, account `workspace-access-key`, and
`kSecAttrSynchronizable = false`. Read additionally asserts match-limit one and
return-data. Add asserts exact UTF-8 bytes and
`kSecAttrAccessibleWhenUnlockedThisDeviceOnly`. Duplicate add performs an
update of that exact identity and never deletes first. Delete is exact and
treats item-not-found as success. Invalid UTF-8 and Security failures remain
distinguishable safe operation/status errors without query data or key text.

The injected connectivity call recorder proves one handler installation, one
private serial queue start, mapping of offline/online values, idempotent cancel,
no callbacks after cancel, and deinit cancellation without retaining the
observer. The live adapter maps only `NWPath.Status.satisfied` to online.

## Secret, URL, UI, and external-contact review

Canary keys were exercised through candidate, restored, Keychain-error, API
error, and `String(describing:)` paths. No observable message contains them.
The raw candidate exists only in the local SwiftUI `@State` and privately in the
retained service key-provider closure; disconnect clears that service. There is
no logging, `UserDefaults`, plist/file persistence, fallback URL, or production
provider code in this package.

The primary `WindowGroup("Find Me Gamer", id: "main")` remains intact and owns
one `@State` session. Its idempotent `.task` restore routes checking to a system
`ProgressView`, missing-key/offline-without-service to the minimal access view,
and authenticated/offline-with-service to the existing placeholder. The access
view has one native `SecureField`, Return submission, focus, safe status copy,
duplicate-submit disabling, a primary Connect action, and Try Again only for
offline access/configuration state. Existing 640 x 420 minimum sizing remains.

Tests use only in-memory fakes and make no backend, Keychain, SMTP, DeepSeek,
Steam, YouTube, S3, or other external-provider contact.

## Real app verification and cleanup

`./script/build_and_run.sh --verify` built and launched the real app bundle.
To honor the binding prohibition on reading/writing/deleting the developer's
actual Keychain item, the launch used the intentionally invalid local-only
verification value `invalid://local-verification`; URL rejection occurs before
Keychain access and makes no backend request. The launched process was exact PID
`999`; it was terminated with `/bin/kill 999`, `kill -0 999` then failed, and
`pgrep -x FindMeGamer` found no remaining process. Bundle inspection confirmed
`CFBundleIdentifier = com.findmegamer.desktop` and
`LSMinimumSystemVersion = 14.0`. Static runner inspection confirms its unchanged
normal `FMGAPIBaseURL` default is `http://127.0.0.1:8000`.

## Files changed

- `macos/Sources/FindMeGamerCore/Services/KeychainStore.swift`
- `macos/Sources/FindMeGamerCore/Services/ConnectivityMonitor.swift`
- `macos/Sources/FindMeGamerCore/Features/AppSession.swift`
- `macos/Sources/FindMeGamer/Views/WorkspaceAccessView.swift`
- `macos/Sources/FindMeGamer/App/FindMeGamerApp.swift`
- `macos/Sources/FindMeGamer/Views/AppRootView.swift`
- `macos/Tests/FindMeGamerCoreTests/AppSessionTests.swift`
- `macos/Tests/FindMeGamerCoreTests/KeychainStoreTests.swift`
- this report

## Bounded concerns

None within the internal-Demo Task 4 boundary. Public/multi-user authentication,
remote logout/revocation, key rotation, malicious Keychain corruption, extreme
concurrency, telemetry, the Task 5 shell/offline banner, polling, and feature UI
remain intentionally out of scope.

## Binding review fix after `a3baa55`

The first independent review identified two ordinary-flow defects. The focused
fix commit uses subject `fix: make workspace retries authoritative`; its exact
content-addressed SHA is reported in the implementer handoff because embedding
the SHA inside its own commit would change that SHA.

### Retry RED/GREEN

The complete regression sequence begins with a missing-key restore, enters a
candidate key, receives a transient validation failure, and invokes the same
action as the visible Try Again control with that still-local candidate.

- RED 1: the reviewed commit did not compile the regression because
  `AppSession` had no `retryAccess` member. This demonstrated the absence of an
  action that can select candidate revalidation instead of stale idempotent
  restore.
- GREEN 1: the regression passed 1/1. The same exact candidate reached the API
  twice, validation ran exactly twice, and the fake store remained untouched
  after the transient failure then saved exactly once after success.
- RED 2: with the no-candidate branch deliberately restored to the reviewed
  idempotent behavior, the retry test failed with fake-store read count 1
  instead of the hand-derived expected 2.
- GREEN 2: candidate and no-candidate retry regressions passed 2/2. A non-empty
  key calls `connect(key:)`; an empty/all-whitespace key explicitly reruns
  restore despite prior `didRestore`.

`WorkspaceAccessView` now sends Try Again through `retryAccess(key:)`. The key
binding is owned by `AppRootView`'s local in-memory `@State`, so the candidate
survives the temporary `.checking` branch that removes and recreates the access
view. It is not observable on `AppSession`, is never persisted before a
successful validation, and is cleared when a service is successfully retained.
Configuration/no-candidate retry continues through the forced restore path.

### Disconnect/recovery RED/GREEN

A test-only continuation gate suspends the second validation after an initial
successful restore and connectivity false/true recovery. The test completes
`disconnectThisMac()` first, then resumes the API despite task cancellation.
It is table-driven over API success and an explicit `CancellationError`.

- RED: success overwrote the disconnected session as `.authenticated` and
  restored a workspace session; cancellation overwrote it as `.offline`.
  Three assertions failed across the two cases on the reviewed implementation.
- GREEN: both cases passed. Final state stayed `.needsKey`, service/session
  stayed nil, the exact fake key was deleted once, and validation count remained
  exactly two.

The fix adds a private, observation-ignored session generation. Every restore,
connect, and recovery validation captures authority and checks both generation
and task cancellation after suspension before committing observable state.
Disconnect increments the generation and clears/cancels restore and recovery
tasks before awaiting local Keychain deletion, then rechecks its own authority
before committing. Stale task cleanup is also generation-guarded so it cannot
clear a newer task reference.

### Final fix verification

- New retry regressions: 2 tests, 0 failures.
- New suspended-recovery regression: 1 parameterized test / 2 completion cases,
  0 failures.
- Full `AppSessionTests`: 19 tests, 1 suite, 0 failures, 0.118 s.
- Focused Keychain/connectivity: 8 tests in 2 suites passed; explicit
  connectivity filter ran 2/2.
- Full Swift suite: 53 tests, 5 suites, 0 failures, 0.115 s.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
- Changed Swift passes `swift format lint --strict`; `git diff --check` passes.
- Safe `./script/build_and_run.sh --verify` launched exact PID `10320` with
  bundle ID `com.findmegamer.desktop` and macOS floor `14.0`; `/bin/kill 10320`
  terminated only that PID and no `FindMeGamer` process remained. As in the
  initial implementation gate, the launch used `invalid://local-verification`
  so the real bundle path was exercised without querying the developer's
  Keychain or contacting a backend; the runner's normal localhost URL remains
  unchanged.
- No backend, OpenAPI, generated output, package manifest, build runner,
  Keychain implementation, connectivity implementation, or Task 5 feature
  surface changed in this fix.

Bounded concerns after the fix: none within the internal-Demo Task 4 boundary.
