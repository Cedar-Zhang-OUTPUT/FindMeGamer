# Task 9 implementation report

## Scope and result

Implemented the Library Analyze Request Inspector on immutable base
`2367436e4b2504f01b9d65c61b76fbd31eede0d7`. The change adds the app-owned
`AnalyzeRequestModel`, a standard right-side macOS Inspector, and the shared
`JobStatusRow`; it modifies `LibraryView` only for Analyze model injection,
badge derivation, Inspector presentation, and exact Profile routing. Task 8's
gallery, Favorite, empty-state, and pagination paths are otherwise unchanged.

Changed files:

- `macos/Sources/FindMeGamerCore/Features/AnalyzeRequestModel.swift`
- `macos/Sources/FindMeGamer/Views/Library/AnalyzeRequestInspector.swift`
- `macos/Sources/FindMeGamer/Views/Shared/JobStatusRow.swift`
- `macos/Sources/FindMeGamer/Views/Library/LibraryView.swift`
- `macos/Tests/FindMeGamerCoreTests/AnalyzeRequestModelTests.swift`
- `macos/Tests/FindMeGamerUITests/AnalyzeRequestPresentationTests.swift`
- this report

No API service, OpenAPI/generated source, JobPoller, LibraryModel, AppSession,
root/sidebar, Package manifest/resolution, backend, card, artwork, or build
runner file changed.

## Genuine RED evidence

Core behavior tests were created before the model. The first required command,
`swift test --package-path macos --filter AnalyzeRequestModelTests`, exited 1
after discovering/compiling the test target with expected errors including
`cannot find 'AnalyzeRequestModel' in scope` and `cannot find`/uninferred
`ReanalysisSource` cases. No production model existed.

Presentation tests were then created before the new UI policy/types. The first
presentation command exited 1 with expected missing `AnalyzeAccessibility`,
`JobStatusPresentation`, and `AnalyzeActionPolicy` compile errors. A later
regression reversed duplicate Job updates and gave a literal failing assertion
(`queued` versus expected `succeeded`); production was changed to retain the
largest `updatedAt`. Exact Profile-route coverage likewise first failed to
compile with missing `AnalyzeProfileRoute` before that view-consumed route was
added.

## Model behavior

- Defaults to Creator and validates the selected target family before any API
  call. It accepts exact HTTPS Steam `/app/<positive decimal id>` and supported
  exact YouTube `/channel/UC…` or `/@handle` URLs, trims only surrounding
  whitespace/newlines, and rejects HTTP, relative URLs, credentials, explicit
  ports, wrong/suffix hosts, and selected-family mismatches with the exact
  required copy.
- Each accepted button action obtains one UUID-style idempotency key and sends
  it once. Submit, per-Job Retry, and per-source Re-analyze have explicit
  in-flight ownership; repeated held clicks are no-ops and no automatic retry
  exists.
- `.job` responses immediately upsert history, clear a stale existing-profile
  result, and invoke the future poller callback once. `.existingProfile`
  exposes exact type/ID/canonical URL without fabricating history or waking
  polling. Failures retain input/history/existing state and display only
  `APIError.description` or stable fallback copy.
- Closing the Inspector changes only presentation state. A held submission
  completes and subsequent shared Job batches continue to merge while closed.
- Batches ignore Match changes, deduplicate by Analysis Job UUID, retain the
  newest `updatedAt` representation, sort by descending `createdAt` with UUID
  tie-break, and derive active count from unique queued/running Jobs.

## Inspector and status presentation

`LibraryView` uses a standard `.inspector` with 320/380/480 point
min/ideal/max widths. The existing header button opens the model-owned
Inspector and its badge derives from `activeJobCount`. The Inspector contains
the required heading, segmented Creator/Game picker, URL field, Submit,
validation/action or existing-Profile banner, divider, and scrollable
`LazyVStack` history.

Identifiers are exactly `analyze.profile-type`, `analyze.url`,
`analyze.submit`, `analyze.existing-profile`, and `analyze.job.<UUID>`.
Queued/running rows use `ProgressView` and exact stage copy; success/failure use
green/red system status symbols; superseded is neutral. Rows show only target
type, canonical URL, submitted time, semantic status, and safe failure text.
They never expose correlation IDs, raw JSON, model metadata, score, or rank.

Submit, Retry, and Re-analyze are disabled offline and only for their relevant
in-flight mutation. History and exact `(ProfileType, UUID)` Open Profile
routing remain available offline. Task 10 owns the eventual Profile Sheet and
Task 17 owns root/poller lifecycle wiring, as required.

## Verification

- Focused Core: 6 tests / 1 suite, 0 failures.
- Focused presentation: 4 tests / 1 suite, 0 failures.
- Full Swift: 103 tests / 11 suites, 0 failures, 0.124 seconds.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0. The
  package's existing generated-target exception continues to emit its known
  generated OpenAPI diagnostics; Core and app sources compile strictly.
- Strict `swift-format` lint passed for all six changed Swift files and
  `git diff --check` passed.
- Scope, manifest/resolution, secret, and tracked-artifact audits passed; no
  runtime network, provider, Keychain, or backend contact was added to tests.
- Safe verification used
  `SERVICE_BASE_URL='invalid://local-verification'
  ./script/build_and_run.sh --verify`, exit 0. The staged bundle has identifier
  `com.findmegamer.desktop`, minimum macOS `14.0`, and the exact invalid test
  URL. Exact launched PID `9326` was terminated, `kill -0` failed afterward,
  and no `FindMeGamer` process remained.

The commit subject is exactly `feat: add analyze request inspector`. The final
commit SHA and immutable review-package byte count/SHA-256 are recorded in the
post-commit handoff because embedding them in this commit would change those
identifiers.

## Bounded concerns

No binding internal-Demo defect is known. Root dependency/lifecycle wiring and
the destination Profile Sheet are intentionally deferred to Tasks 17 and 10;
app relaunch history persistence and extreme/adversarial input or Job-history
scales remain explicitly outside Task 9.
