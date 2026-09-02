# Task 3 implementation report

## Outcome

Implemented the complete app-owned domain boundary and all 32 `APIService`
methods on immutable base `0b28924318d78ba9d82f75c267c29f0544c16362`.
`OpenAPIService` uses the generated `Client`, `URLSessionTransport`, and the
authenticated middleware; generated request/response/runtime types terminate at
the internal service/mapper boundary. The required commit subject is
`feat: add macos api domain boundary`. The final commit SHA and immutable review
package digest are emitted in the task handoff because a file contained in a
commit cannot embed that commit's own SHA or its own base-to-HEAD diff digest
without changing both values.

## Strict TDD record

1. Domain RED: after adding only `DomainMappingTests.swift`, ran
   `swift test --package-path macos --filter DomainMappingTests`. Compilation
   failed as expected because `DomainMapper`, `APIError`, and the domain types
   did not exist.
2. Domain GREEN: added the smallest app-owned model families and generated-type
   mapper. The exact focused command passed 5 tests in 1 suite, 0 failures.
3. Service RED: added recording-transport tests before the protocol/service.
   `swift test --package-path macos --filter OpenAPIServiceTests` failed to
   compile because `APIService` and `OpenAPIService` did not exist.
4. Service GREEN: implemented the protocol, generated client wrapper, and auth/
   error middleware. The focused service suite passed 7 tests, 0 failures (the
   non-2xx test has four parameter cases).
5. SMTP ruling RED/GREEN: first added the non-nil draft test; it failed because
   the implementation contacted transport. The implementation now throws exact
   local code `smtp_draft_test_unsupported`, message
   `Save the email settings before testing the connection.`, and
   `retryable == false`, with zero requests. `nil` still calls the generated
   bodyless endpoint.
6. Malformed-success RED/GREEN: a malformed HTTP 200 initially surfaced a raw
   `DecodingError`; the service now maps generated decoding failures to safe
   non-retryable `invalid_response`.
7. Refactor: moved generated-type conversion into the explicitly allowed
   internal `DomainMapper.swift`, leaving `OpenAPIService.swift` responsible for
   API calls and success-shape selection only. Final combined task-focused run:
   12 tests in 2 suites, 0 failures.

## Coverage and boundary evidence

- Literal generated fixtures cover Game/Creator cards and details, recursive
  JSON, nil timestamps/cursors, manual/discovered/unavailable contacts, queued
  and existing-Profile Analysis submissions, changed Analysis/Match jobs,
  qualitative Match detail, Outreach Campaign/Batch/Delivery/Template/preview,
  configured/unconfigured SMTP, reanalysis, and connection status.
- Match mapping preserves the two backend arrays' order but exposes no numeric
  score, rank, total/dimension score, backend-order, or array-position property.
- The service boundary test invokes every one of the 32 protocol methods through
  the actual generated client and records 37 requests. It verifies routing for
  both Profile types, paging/search/collection/job query values, nil/value
  Creator manual fields, Template create/update, and consumer-visible mapped
  results.
- All six caller-owned action keys (Analysis create/retry, Match create/retry,
  Send Batch create, Delivery resend) appear exactly once, unchanged, and no
  automatic retry occurs. Settings and Template mutations invent no key.
- Every recorded request has exact Bearer authentication and injected
  correlation. Blank keys and unsaved Template/SMTP drafts fail before transport.
- Realistic 401, 409, 422, and 500 global envelopes map before generated error
  decoding. Response correlation takes precedence; malformed errors use stable
  `http_<status>` plus a generic message and never echo raw bodies. Transport
  failures remain underlying failures.
- Canary workspace key, SMTP password, and replacement connection secret do not
  occur in returned objects or error descriptions. SMTP password and connection
  secret exist only in intentional write request inputs; no response/status type
  stores them.

## Files changed

- Updated `macos/Package.swift` only for Core/test dependencies and the
  generator-only warning exception.
- Added six focused model files under
  `macos/Sources/FindMeGamerCore/Models/`.
- Added `APIService.swift`, `OpenAPIService.swift`,
  `WorkspaceAuthMiddleware.swift`, and internal `DomainMapper.swift` under
  `macos/Sources/FindMeGamerCore/Services/`.
- Added `DomainMappingTests.swift` and `OpenAPIServiceTests.swift`.
- Added this report. Backend files, both OpenAPI documents, generated output,
  and `Package.resolved` were not modified.

## Final verification

- `swift test --package-path macos --filter DomainMappingTests`: 5 tests / 1
  suite / 0 failures.
- `swift test --package-path macos`: 26 tests / 2 suites / 0 failures, including
  all Task 1/2 contract and nullable-generation tests.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: passed from a
  clean SwiftPM build. A plain target argument was first proven ineffective
  because SwiftPM placed the package-wide strict flag later. The target-local
  `-Xfrontend -no-warnings-as-errors` produces actual frontend order
  `-warnings-as-errors`, then `-no-warnings-as-errors` for `FindMeGamerAPI`;
  `FindMeGamerCore` has only `-warnings-as-errors`.
- Remaining warning output is generator-owned only: OpenAPIKit's existing 3.1
  `nullable`/`null` schema diagnostics and generator 1.13.1 unused public imports
  in empty split files. There are no app-owned Core/App warnings.
- `./script/build_and_run.sh --verify`: passed and launched PID 85562; that exact
  PID was terminated and no FindMeGamer app process remains.
- `xcrun swift-format lint --strict --recursive` over Core and the two new test
  files: passed. `git diff --check`: passed.
- Copied schema SHA-256 remains
  `7a8dc801d3d3c0c69bf413f7de5628430ca15b83a24972b24df5c67c38baf507`;
  it still contains exactly 42 operations. `Package.resolved` SHA-256 remains
  `68728549752b4e233aa7748e3268217c00f7cd115a49dc2c86d644ef657e363d`.
- Base-scoped checks found no backend, copied-schema, lockfile, or generated
  source edits; public declaration scans found no generated type leakage; scans
  found no placeholder/fatal paths.

## Self-review and bounded concerns

Every protocol method has one complete implementation; expected normal success
variants are mapped, invalid UUIDs/impossible unions fail safely, timestamps and
opaque cursors are preserved, and public values are `Sendable`. Normal coworker
flows have no known blocker. The existing generator diagnostics above remain a
bounded toolchain/schema concern and are intentionally not addressed by editing
the authoritative schema or generated output in this task.
