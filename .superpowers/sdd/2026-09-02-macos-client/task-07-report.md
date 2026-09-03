# Task 7 implementation report

## Outcome and scope

Implemented the app-owned Library feature model against immutable base
`dc2ada30b8903d91977db464b9af16d394369013`. Production and test changes are
limited to the two files required by the brief: `LibraryModel.swift` and
`LibraryModelTests.swift`; this report is the only additional tracked artifact.
No API/OpenAPI/generated output, AppSession, JobPoller, UI, package manifest,
backend, build runner, or existing production file changed.

The required commit subject is `feat: manage profile library state`. Its exact
commit SHA and immutable base-to-HEAD review-package byte count/SHA-256 are
reported in the post-commit handoff. Those content identifiers cannot be
embedded in a file inside the same single commit without changing the values
they identify.

## TDD evidence

### RED

Behavior-first `LibraryModelTests` and its deterministic actor fake were added
before production code. After correcting a test-only nested-type visibility
typo, the binding command

```text
swift test --package-path macos --filter LibraryModelTests
```

failed at compile time with the required genuine missing-type error:
`cannot find 'LibraryModel' in scope` (followed by expected type-inference
cascades at its call sites).

### GREEN and refactor REDs

The smallest initial implementation made the then-nine-test focused suite
GREEN. Subsequent contract-strengthening tests produced three genuine behavior
REDs before their minimal fixes:

- selecting the still-default unloaded Creator type initially issued no load;
- a queued immediate load could bypass a newer search's 300 ms debounce;
- a Favorite failure arriving while a newer search debounce was pending did
  not restore the still-visible optimistic card.

The implementation now generation-fences scheduled and in-flight list work and
uses the exact optimistic snapshot to decide whether Favorite rollback remains
applicable. A cancellation-checking API fake was also used as a mutation check;
the debounce contract remained GREEN.

Final focused result:

```text
Suite LibraryModelTests passed
Test run with 15 tests in 1 suite passed
```

The complete focused suite then passed 3/3 consecutive additional runs.

## Production behavior

- `@MainActor @Observable LibraryModel` holds independent Creator and Game
  controls, items, opaque cursor, selection, loading/error/highlight state, and
  loaded/dirty ownership. The public state contains only Core domain types.
- Search changes are visible immediately and use one cancellable, exact 300 ms
  `AppClock` debounce. Only Collection schedules an immediate page-one load.
  Every request captures type/query/filter and uses limit 50.
- Page-one and page-next operations use per-type generations. Stale successes
  and failures cannot mutate newer items, cursor, loading flags, or errors.
  Paging passes the opaque cursor unchanged and appends first-seen UUIDs in
  server order without reordering existing cards.
- List failures preserve visible items and usable cursor, expose only `Could
  not load profiles.`, and retain a safe API correlation ID when present.
- Favorite updates flip before awaiting, allow one request per ID, fence
  already-started list completions, apply only a matching canonical type/ID,
  remove confirmed unfavorites from Only Collection, and restore the exact
  original card/order on failure or mismatch with `Could not update favorite.`
  No retry is added.
- Successful Analysis changes are accepted only when their profile ID is also
  in the affected-ID list. The selected type refreshes once and highlights the
  last present affected profile for exactly two clock seconds; a newer token
  owns its own expiry. Inactive affected types become dirty and refresh once
  when selected. Running/failed/unrelated Analysis and Match changes do not
  reload the Library.

## Deterministic test coverage

The actor API fake records literal type/query/filter/cursor/limit and Favorite
calls, scripts pages/errors, and holds completions behind checked-continuation
gates. The committed `ManualClock` owns every debounce/highlight advance. No
real network, provider, Keychain, multi-second sleep, database, UserDefaults,
or singleton is touched.

Tests prove distinct per-type state and default loading; exact debounce and
filter snapshots; immediate-load invalidation; stale success/failure fencing;
failure copy/correlation preservation; exact cursor paging, one-in-flight
suppression and ordered de-duplication; optimistic Favorite single-flight,
canonical success, Only Collection removal, list fencing, mismatch/failure
rollback, and rollback during a new debounce; selected Analysis refresh and
last-ID highlight timing/token renewal; and inactive dirty refresh-on-select.

## Full verification

- Focused Library suite: 15 tests / 1 suite, 0 failures; repeated 3/3.
- Full Swift suite: 83 tests / 8 suites, 0 failures, 0.128 s.
- `swift build --package-path macos -Xswiftc -warnings-as-errors`: exit 0.
  Existing generated-target OpenAPI diagnostics remain under its pre-existing
  warning exception; Core/App sources compiled strictly.
- Both changed Swift files pass `swift-format lint --strict`; `git diff
  --check` passes.
- Scope, secret, and artifact checks find only the two required source/test
  files plus this report, with no credential string, generated/build artifact,
  provider call, or temporary file tracked.

## Safe app launch and cleanup

`SERVICE_BASE_URL='invalid://local-verification'
./script/build_and_run.sh --verify` built and launched the actual app without a
usable backend URL. The staged bundle retained identifier
`com.findmegamer.desktop`, minimum macOS `14.0`, and the intentional invalid
verification URL. The exact launched PID was `58328`; `kill 58328` terminated
only that process, `kill -0 58328` then failed, and `pgrep -x FindMeGamer`
found no remaining process.

## Bounded concerns

None within the stable company-internal Demo boundary. Task 8 owns Library UI,
profile sheets, Analyze submission, and root wiring. Extreme input rates,
malicious payloads, huge-library optimization, persistent/offline caching, and
public multi-tenant synchronization remain intentionally out of scope.

## Independent-review fix round 1

### Finding and regression RED

The review found that Favorite used the same `listGeneration` needed by a
pending Search debounce or queued Only Collection reload. Toggling Favorite
therefore made the scheduled current-criteria load silently return without an
API request, leaving old cards under new controls. A queued filter request that
had already begun could likewise be discarded with its returned cursor.

Three production-coupled tests were added first. Against commit
`51bd9d57d99173a9da6e91a2a699595a470bc680`, the two Search cases both failed
at literal `reloadStarted` expectations because the second list request never
occurred. The Only Collection case failed because `nextCursor` remained `nil`
instead of the literal `filtered-cursor`. This was the required genuine
behavior RED.

The regressions exercise both response orderings: a current Search result
lands while Favorite success is held, and another current Search result lands
after Favorite failure. The queued Only Collection request is held until after
canonical Favorite success. They assert one mutation, the exact latest list
arguments, canonical/rollback favorite value, current cursor, and stable
Favorite error ownership.

### Minimal ownership separation

Each type now has a criteria generation and an explicit pending-reload bit
separate from list-response generation. Search/filter changes and scheduled
loads own the former; ordinary newer/stale list requests own the latter.
Favorite still invalidates unrelated old list work, but preserves the one
reload required by the user's current query/filter.

Per-profile Favorite overlays carry a monotonic revision, the optimistic or
settled canonical/rollback card, and in-flight state. A preserved current-list
request captures the revisions it began with and reconciles only profiles
whose Favorite changed while it was active. This accepts the current page and
cursor without allowing it to overwrite optimistic, canonical, or rolled-back
state. Confirmed unfavorites remain excluded from Only Collection while an
optimistic unfavorite remains visible until confirmation, preserving the
original contract.

Error revisions ensure a later successful list completion cannot clear a
Favorite failure that completed after that list request began. A genuinely
later list failure may still become the current visible error. No API, UI,
AppSession, JobPoller, generated output, package, backend, retry, persistence,
or provider behavior changed.

### Fix verification

- Exact Search regressions: 2/2 GREEN.
- Exact queued Only Collection regression: 1/1 GREEN.
- Complete focused Library suite: 18 tests / 1 suite, 0 failures; repeated 5/5.
- Full Swift suite: 86 tests / 8 suites, 0 failures, 0.120 s.
- Strict Swift build with `-warnings-as-errors`: exit 0. Existing diagnostics
  are limited to the generated target's pre-existing warning exception.
- Both changed Swift files pass strict `swift-format`; `git diff --check` and
  scope/secret/artifact checks pass.
- Safe invalid-URL app verification launched exact PID `69536`; that PID was
  terminated, `kill -0` failed afterward, and no `FindMeGamer` process
  remained. The staged bundle contains `invalid://local-verification`.

The fix commit subject is `fix: preserve library reloads during favorites`.
Its exact SHA and immutable fix-package byte count/SHA-256 are recorded in the
post-commit handoff because embedding those values in this same commit would
change the identifiers being reported.
