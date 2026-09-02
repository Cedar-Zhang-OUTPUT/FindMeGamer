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
