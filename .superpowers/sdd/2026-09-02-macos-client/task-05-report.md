# Task 5 implementation report

## Outcome

Implemented the native macOS workspace shell against immutable base
`02211b88a4aaa0470fe81a5195774982d9952ce0`. The authenticated and retained-
service offline states now share one stable two-column `NavigationSplitView`
with the exact four destinations, independent navigation paths, a detail-only
offline treatment, and root-level persisted appearance application. Task 4
access/session behavior is unchanged.

The required single commit uses subject
`feat: add native macos workspace shell`. Its final content-addressed SHA and
immutable base-to-HEAD review byte count/SHA-256 are reported in the handoff;
they cannot be embedded inside the same commit whose content they identify
without changing those values.

## TDD evidence

### Initial RED

Added `AppDestinationTests.swift` before production code and ran the binding
command:

```text
swift test --package-path macos --filter AppDestinationTests
```

Compilation failed for the expected reason: `AppDestination`,
`AppearanceMode`, `FontSizePreference`, and `WorkspaceAvailability` were all
missing. This was a genuine missing-production-type RED, not an environment or
fixture failure.

### Initial GREEN and UI implementation

Added the smallest Core policies for destination restoration, appearance raw-
value restoration, dynamic type/color-scheme mapping, and workspace
availability. The focused command passed 4 tests in 1 suite. The SwiftUI shell
was then added from those policies and compiled successfully in the same
focused build.

### Navigation-retention RED/GREEN

Self-review identified that separate SwiftUI branches for `.authenticated` and
retained-service `.offline` could recreate the root on a normal connectivity
transition and discard all four paths. A new literal state-matrix test was
added first. It failed to compile because `WorkspaceRootSurface` did not exist.
The minimal policy now maps both states with a retained service to the same
`.workspace` branch, while checking stays on Progress and missing-service states
stay on access. Final focused result: 5 tests in 1 suite, 0 failures.

## Destination and selection contract

- `AppDestination` is public, raw-string, `CaseIterable`, `Identifiable`,
  `Sendable`, and `Hashable`.
- Literal tests prove exact order `library`, `match`, `outreach`, `settings`;
  exact titles `Library`, `Match`, `Outreach Management`, `Settings`; exact SF
  Symbols `square.grid.2x2`, `person.2.badge.magnifyingglass`, `paperplane`, and
  `gearshape`; and string IDs matching raw values.
- There are exactly four destinations. Literal obsolete values `analyze` and
  `match-results`, nil, empty, and corrupt strings all restore as Library.
- `AuthenticatedRootView` owns raw per-window selection using exact
  `@SceneStorage("sidebar-selection")`. The binding sanitizes nil/unknown values
  to Library and writes only valid raw values.
- `SidebarView` is a flat native `.sidebar` `List(selection:)`. Every row is a
  single system `Label` plus its selection tag; there are no cards, inline
  status strips, opaque pane backgrounds, custom blur, glass, or AppKit.

## Navigation and offline behavior

- The shell owns four distinct `@State NavigationPath` values: Library, Match,
  Outreach, and Settings. Each destination selects its corresponding
  `NavigationStack(path:)`; sidebar switching never clears any other path.
- Each stack currently renders only the exact destination title as a semantic
  placeholder. No fake business data or later feature model/view was added.
- `WorkspaceRootSurface` keeps authenticated and retained-service offline
  states on one stable workspace branch, preserving root-owned paths across
  connectivity loss/recovery. Checking, needs-key, and offline-without-service
  continue to follow Task 4 behavior.
- `OfflineBanner` appears inside the detail column, above rather than instead of
  the selected stack, only for `.offline`. Its Retry button calls the existing
  safe `retryAccess(key: "")` forced-restore path.
- A narrow shell-owned `workspaceWritesEnabled` environment value receives the
  pure `WorkspaceAvailability` policy. It is false only offline and true while
  authenticated; tests prove reads and navigation stay enabled in both states.
  The split view, sidebar, reads, and appearance are not disabled, and no queue
  or automatic write retry was introduced.

## Appearance behavior

- `AppearancePreferences` uses SwiftUI `@AppStorage` with exact keys
  `appearance-mode` and `font-size`.
- Literal tests prove exact stored appearance values `system`, `light`, `dark`
  and English titles, with System default/fallback mapping to nil color scheme.
- Literal tests prove exact font values `small`, `medium`, `default`, `large`,
  `extra-large`, exact English titles, and required mappings to `.small`,
  `.medium`, `.large`, `.xLarge`, and `.xxLarge`. Nil/corrupt storage falls back
  to Default.
- The modifier is applied to `AppRootView` after its state-routing group, so it
  covers Progress, Workspace Access, and authenticated/offline workspace
  surfaces. No settings controls, hardcoded colors, or manual global defaults
  mutation were added.

## Verification

- Focused: `swift test --package-path macos --filter AppDestinationTests` ->
  5 tests / 1 suite / 0 failures.
- Full: `swift test --package-path macos` -> 58 tests / 6 suites / 0 failures,
  including all prior API, domain, Keychain, connectivity, and AppSession tests.
- Strict compile: `swift build --package-path macos -Xswiftc -warnings-as-errors`
  -> exit 0. Task 5 Core/App sources emit no warnings; output contains only the
  previously bounded generator OpenAPI/schema and empty split-file diagnostics.
- Real bundle: `SERVICE_BASE_URL='invalid://local-verification'
  ./script/build_and_run.sh --verify` -> exit 0 and exact PID `22086`. The
  invalid scheme is rejected before Task 4 Keychain access and performs no
  backend/provider call. Staged plist inspection showed bundle ID
  `com.findmegamer.desktop`, macOS floor `14.0`, and the exact safe invalid URL.
  `/bin/kill 22086` terminated only that process; `kill -0` failed afterward and
  `pgrep -x FindMeGamer` returned nothing.
- Strict Swift format over every changed Swift file -> exit 0. `git diff
  --check` -> exit 0.
- Scope checks show no change to `Package.swift`, `Package.resolved`, backend,
  OpenAPI/generated API, AppSession/Keychain/connectivity semantics, build
  runner, product identity, `WindowGroup("Find Me Gamer", id: "main")`, or the
  normal runner default `http://127.0.0.1:8000`.
- No credentials, `.build`, `dist`, app bundle, or generated output are tracked.
  Tests are pure local policy tests and contact no backend or provider.

## Files changed

- `macos/Sources/FindMeGamerCore/Models/AppDestination.swift`
- `macos/Sources/FindMeGamer/Views/SidebarView.swift`
- `macos/Sources/FindMeGamer/Views/AuthenticatedRootView.swift`
- `macos/Sources/FindMeGamer/Views/Shared/OfflineBanner.swift`
- `macos/Sources/FindMeGamer/Support/AppearancePreferences.swift`
- `macos/Sources/FindMeGamer/Views/AppRootView.swift`
- `macos/Tests/FindMeGamerCoreTests/AppDestinationTests.swift`
- this report

## Bounded concerns

None within the company-internal Demo Task 5 boundary. Feature content,
appearance controls, polished visual treatment/Liquid Glass, keyboard command
systems, and multi-window stress remain deliberately assigned to later work.
