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

## Independent-review fix round 1

### Finding and regression RED

The review found that the pagination `.task` was attached to the clear
sentinel branch that disappeared as soon as `isLoadingNextPage` became true.
That transition could cancel its own awaited model request. Separately, the
permanent `lastPageRequest` marker suppressed cursor A forever after Task 7
invalidated an in-flight next page while retaining that cursor, such as a
Favorite during paging.

Two production-coupled tests were added first against commit
`b165317eb2c3347f85105f6352c877ad7d9be401`. The focused command discovered the
existing suite and failed compilation with the intended missing production
types: `cannot find 'LibraryPaginationCoordinator' in scope`, `cannot find
'LibraryRetryPolicy' in scope`, and the related request/observation types. This
was a genuine behavior-first RED rather than a zero-test result.

The primary regression uses the real Task 7 `LibraryModel`, a controlled API
actor whose page gate deliberately ignores cancellation, and a real Favorite
mutation. It holds cursor A's next page, invalidates that model generation via
Favorite, observes the retained cursor, and then releases the stale request.
It requires maximum list concurrency one, no stale page commit, one replacement
only after the old await exits, preserved canonical Favorite, and the new page
and cursor in server order.

The second regression makes cursor A fail normally. It requires the safe shared
error, no automatic third call after actor yields, manual next-page Try Again
before the third call, successful append/clear, first-page error routing, same-
cursor page-one rearming, and natural task-key change when criteria changes.

### Minimal fix

The footer now keeps one stable outer `ZStack` and `.task` identity while its
inner content changes between the invisible sentinel and small progress state,
so the loading flag no longer removes and cancels its own task. A small
`@MainActor @Observable` coordinator owns only UI scheduling state; the model
continues to own all list data, generation, loading, error, and API behavior.

The coordinator allows one active next-page await. An invalidation returning to
the same eligible cursor records a replacement intent but cannot start it until
the old await actually exits; a revision then permits exactly one current-key
replacement. A task arriving under changed criteria while old work retires is
similarly queued as the latest request. Request identity includes profile type,
exact query, collection filter, and byte-preserved opaque cursor.

A normal failed next page records its request and does not change revision, so
it cannot auto-loop. Shared `Try Again` routes that exact current failure to a
single next-page retry; all other errors still call `loadFirstPage()`. Starting
a page-one recovery clears an old next-page failure marker, and completion
rearms the same cursor only when that cursor was already attempted before the
recovery, avoiding an initial-load double trigger.

No Task 7 model/API, root, manifest, backend, generated output, artwork/card,
or later feature changed. The pre-existing transient empty-state flash and
unused `headerRowCount` constant remain the explicitly nonblocking follow-ups.

### Fix verification

- Focused `LibraryStructureTests`: 7 tests / 1 suite, 0 failures.
- Full Swift suite: 93 tests / 9 suites, 0 failures, 0.129 s.
- Strict `-warnings-as-errors` build: exit 0; only the pre-existing generated-
  target diagnostics remain under its existing scoped exception.
- Both changed Swift files pass strict `swift-format`; `git diff --check`,
  manifest/dependency, scope, secret, artifact, and unchanged-resolution checks
  pass.
- Safe invalid-URL app verification retained bundle ID
  `com.findmegamer.desktop`, macOS `14.0`, and the exact invalid URL. It launched
  PID `89446`; only that PID was terminated and no app process remains.

The fix commit subject is `fix: recover library pagination`. Its exact SHA and
immutable fix-package byte count/SHA-256 are recorded in the post-commit
handoff because embedding those values here would change the identifiers.

## Independent-review fix round 2

### Remaining finding and RED

The scoped re-review identified one ordinary Only Collection path not covered
by round 1. If its single visible Favorite was removed during cursor A's active
next-page request, Task 7 correctly removed the card and retained cursor A, but
`LibraryView.libraryContent` switched to its standalone empty branch. That
destroyed the entire ScrollView/footer task host before the coordinator could
launch its deferred replacement, producing a false final empty Library while a
later page remained.

The existing real-model regression was changed first to use Only Collection,
an initially favorited sole card, and a canonical unfavorite result while the
next page was held. It now requires `model.items.isEmpty`, retained cursor A,
the correct empty-state presentation inside a scrollable pagination host,
maximum list concurrency one, and the later replacement card/cursor. Against
round-1 commit `5f546ffedef657762da5f51cf07e7af986214f05`, the focused command failed
compilation with the expected `cannot find 'LibraryContentPolicy' in scope`
and missing `keepsPaginationHost` errors. The existing seven-test suite was
discovered; this was not a zero-test RED.

### Minimal fix and evidence

One deterministic `LibraryContentPolicy`, consumed directly by the real view,
selects initial loading, standalone empty, or scrollable content. With no
cards, any retained next cursor, next-page loading state, or active/pending/
failed coordinator recovery keeps the ScrollView, adaptive grid, and pagination
footer alive. The same scrollable surface renders the required `No profiles
found.` state while empty, so retaining the task host does not fabricate cards
or hide the empty result. Normal no-cursor empty and initial-loading branches
remain unchanged.

The modified production-coupled test passes through the actual Task 7 model:
the sole card is removed, cursor A remains, the policy selects
`.scrollable(showEmptyState: true)`, the stale gated result does not commit, and
exactly one replacement returns the next card with maximum concurrency one.
No coordinator scheduling algorithm, Task 7 model/API, root, manifest, backend,
generated output, or unrelated Library UI changed.

- Focused `LibraryStructureTests`: 7 tests / 1 suite, 0 failures.
- Full Swift suite: 93 tests / 9 suites, 0 failures, 0.132 s.
- Strict warnings-as-errors build: exit 0; only pre-existing generated-target
  diagnostics remain under its scoped exception.
- Changed files pass strict Swift format, `git diff --check`, manifest/
  dependency, scope, secret, artifact, and resolution checks.
- Safe invalid-URL app verification retained the expected bundle identity,
  macOS `14.0`, and invalid URL. Exact PID `96258` was terminated and no app
  process remains.

The round-2 commit SHA and fix-only review-package bytes/SHA-256 are recorded
in the post-commit handoff because embedding them here would change them.
