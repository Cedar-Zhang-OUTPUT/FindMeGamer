# Task 8 implementation report

## Outcome and scope

Implemented the native Library workspace on immutable base
`62f9d2b98ec8cdbf360f009635ac7bfe7e29323e`. The change is limited to the five
required Library/shared SwiftUI files, one required UI-test file, the minimal
`FindMeGamerUITests` target in `macos/Package.swift`, and this report. No
LibraryModel, API, AppSession, JobPoller, OpenAPI/generated output, backend,
root/sidebar, build runner, dependency resolution, or later feature changed.

The required commit subject is `feat: build profile library workspace`. Its
exact commit SHA and immutable base-to-HEAD review-package byte count/SHA-256
are reported in the post-commit handoff because embedding those identifiers in
this same commit would change the values they identify.

## TDD evidence

### RED

The minimal executable-module UI-test target and five behavior-first tests were
added before production code. The binding focused command discovered the suite
and failed compilation with the expected missing production symbols, including
`cannot find 'LibraryLayout' in scope`, `cannot find 'LibraryCopy' in scope`,
`cannot find 'GameCardPresentation' in scope`, and `cannot find
'ArtworkURLPolicy' in scope`; it was not a zero-test result. The first RED also
showed that the Core fixtures needed `@testable import FindMeGamerCore` to use
their internal synthesized initializers, which was corrected only in the test
without changing Core production API.

### GREEN and refactor

The smallest production implementation established the tested policies and
real SwiftUI hierarchy. One compiler diagnostic then identified a local
pattern-binding name redeclaration in the safe string-list extractor; renaming
that local binding fixed the root cause. The focused suite passed, all changed
Swift/manifest files were formatted, and the post-format focused run was:

```text
Suite LibraryStructureTests passed
Test run with 5 tests in 1 suite passed
```

## Production behavior

- `LibraryView` receives the existing `LibraryModel`, active Analysis count,
  Analyze closure, and profile-open closure. On appearance it asks the model's
  selection contract to ensure the selected type is loaded without owning a
  service or forcing a clean cached reload.
- `LibraryHeader` has exactly two visual rows. The first contains the native
  segmented Game/Creator picker, checkbox Only Collection control, optional
  positive-count badge, and Analyze Request button; the second contains the
  leading `Search Profiles…` field capped at 360 points. All bindings call the
  existing model methods directly.
- The gallery is a native `ScrollView` and `LazyVGrid` with one adaptive
  240–340 point column policy. It retains cards with shared errors and Try
  Again, presents centered initial progress and concise empty state, and uses
  one task per composite type/query/filter/opaque-cursor exposure plus the
  model's in-flight guard for pagination.
- Game and Creator cards read only allowlisted card fields: public short
  description/performance evidence `value`, primary genre/content arrays,
  numeric subscribers, approved artwork URLs, and contact availability. Wrong
  JSON shapes and hidden rank/score keys cannot enter the presentation.
- Open-card and Favorite are sibling buttons with distinct closures and exact
  UUID accessibility identifiers. Favorite uses the model's optimistic card,
  disables only its in-flight ID, and is disabled with Analyze while offline;
  switching, search, filter, pagination, scrolling, and opening remain enabled.
- Highlighting uses a semantic accent outline. Styling uses semantic system
  colors, standard controls, and modest corners without material recreation,
  custom glass/shaders, or hosted AppKit views.
- `AsyncArtwork` accepts only absolute host-bearing HTTP(S) URLs, uses one
  `URLSession` with `URLCache.shared` and protocol cache policy, validates HTTP
  2xx plus `NSImage` decoding, and renders aspect-fill with semantic loading and
  fallback states. SwiftUI task cancellation and a per-request identity fence
  prevent a late old URL from replacing a newer image. It adds no persistence,
  custom cache directory, response logging, or synchronous network work.

## Deterministic test coverage

Five tests prove the literal two-row/copy/accessibility/dimension/type-order
contract; positive-only badge policy; representative Game/Creator public JSON
extraction including evidence values, numeric subscribers, three tags, artwork,
favorite, and contact status; unavailable behavior for wrong shapes and
internal canaries; HTTP(S)-only artwork URL validation; and the actual loader's
system-cache/protocol-policy configuration. Tests make no network, API,
Keychain, provider, database, or image-download request. The production code
review confirms open and Favorite use structurally independent sibling buttons.

## Full verification

- Focused UI suite: 5 tests / 1 suite, 0 failures.
- Full Swift suite: 91 tests / 9 suites, 0 failures, 0.119 s.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
  Core/App sources compiled strictly. Output warnings are only the pre-existing
  OpenAPI generator schema diagnostics and generated split-file unused-public-
  import warnings covered by the already-scoped FindMeGamerAPI exception.
- Changed Swift and manifest files pass `xcrun swift-format lint --strict`;
  `git diff --check`, package manifest dump, dependency resolution inspection,
  scope, secret, tracked-artifact, and unchanged-`Package.resolved` checks pass.
- The manifest adds only `FindMeGamerUITests` depending on the executable and
  Core targets; all products, package pins, generated warning exception, and
  the macOS 14 floor are unchanged.

## Safe app launch and cleanup

`SERVICE_BASE_URL='invalid://local-verification'
./script/build_and_run.sh --verify` rebuilt, staged, and launched the real app
without a usable backend URL. The staged bundle has identifier
`com.findmegamer.desktop`, `LSMinimumSystemVersion` `14.0`, and the exact
intentional invalid URL. The launched PID was `81110`; only `kill 81110` was
used, `kill -0 81110` then failed, and `pgrep -x FindMeGamer` found no remaining
process.

## Bounded concerns

None within the stable company-internal Demo boundary. Task 9/10 own Analyze
and profile destinations, and Task 18 owns root wiring, so this task exposes
closures without fake navigation. Pixel tuning, screenshot matrices, extreme
window sizes or image volumes, malicious image defense, public-scale image
pipelines, and persistent/offline image caching remain intentionally out of
scope.
