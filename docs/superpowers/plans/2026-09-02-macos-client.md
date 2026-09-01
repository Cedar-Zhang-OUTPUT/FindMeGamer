# macOS SwiftUI Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete native macOS 14+ Find Me Gamer client with the four approved workspaces, generated type-safe API access, shared cloud state, native desktop interactions, and official Liquid Glass enhancement on macOS 26+.

**Architecture:** A SwiftPM GUI package has separate generated API, domain/core, and executable UI targets. `AppSession` owns authentication and connectivity; one focused `@Observable` model owns each feature; views receive those models explicitly. SwiftUI `NavigationSplitView`, independent feature `NavigationStack`s, system Sheet, and Inspector provide structure, while availability-isolated wrappers apply only Apple-provided glass APIs on macOS 26 and standard system controls on macOS 14–15.

**Tech Stack:** Swift 6.3, SwiftPM, SwiftUI, Observation, URLSession, Security/Keychain, Network framework, Swift OpenAPI Generator 1.13, OpenAPI Runtime 1.12, OpenAPI URLSession 1.3, Swift Testing.

**Spec:** `docs/superpowers/specs/2026-09-02-find-me-gamer-design.md`

## Global Constraints

- Minimum deployment target is macOS 14 Sonoma; macOS 26-only APIs are isolated with availability checks.
- The app is English-only and has no localization picker.
- Sidebar destinations are exactly Library, Match, Outreach Management, and Settings.
- Analyze Request is a right-side Library Inspector; Match Result lives inside Match navigation.
- The client stores only the Workspace Access Key in Keychain and appearance preferences in AppStorage; it has no SwiftData/Core Data business cache.
- Generated OpenAPI types never flow directly into Views; domain mapping occurs in the API service boundary.
- Library search is server-side and debounced; lists use cursor pagination.
- Job updates use three-second polling only while work is active; the client has no WebSocket or push channel.
- The UI never defines or renders numeric Match score, numeric dimension score, or ordinal rank.
- Standard SwiftUI controls come first. No custom blur, shader, or Liquid Glass imitation is allowed.
- On macOS 26+, official glass treatment is limited to Match Hero, batch Outreach bar, and Analyze status surface; gallery cards stay flat.
- Every task follows TDD and ends with a focused commit.

## File Map

- `macos/Package.swift` — executable, core, API, and test targets with Apple OpenAPI dependencies.
- `macos/Sources/FindMeGamerAPI/` — committed OpenAPI document/config and generated-code host target.
- `macos/Sources/FindMeGamerCore/Models/` — app-owned value models that exactly match visible product concepts.
- `macos/Sources/FindMeGamerCore/Services/` — API protocol/client, auth middleware, Keychain, connectivity, and Job polling.
- `macos/Sources/FindMeGamerCore/Features/` — `@MainActor @Observable` Library, Match, Outreach, and Settings models.
- `macos/Sources/FindMeGamer/App/` — `@main`, activation delegate, root scene, and session ownership.
- `macos/Sources/FindMeGamer/Views/` — focused root, shared, and feature SwiftUI views.
- `macos/Sources/FindMeGamer/Support/` — semantic formatting, appearance, adaptive glass, and view helpers.
- `macos/Tests/FindMeGamerCoreTests/` — service mapping and feature-model behavior tests.
- `macos/Tests/FindMeGamerUITests/` — structural rendering/availability tests that do not require a real server.
- `script/build_and_run.sh` — one kill/build/stage `.app`/launch entrypoint.
- `script/sync_openapi.sh` — deterministic backend-to-Swift API schema sync.
- `.codex/environments/environment.toml` — Codex Run action wired to the build script.

---

### Task 1: SwiftPM GUI scaffold, app bundle runner, and Codex Run action

**Files:**
- Create: `macos/Package.swift`
- Create: `macos/Sources/FindMeGamerCore/FindMeGamerCore.swift`
- Create: `macos/Sources/FindMeGamer/App/FindMeGamerApp.swift`
- Create: `macos/Sources/FindMeGamer/App/AppDelegate.swift`
- Create: `macos/Sources/FindMeGamer/Views/AppRootView.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/PackageSmokeTests.swift`
- Create: `script/build_and_run.sh`
- Create: `.codex/environments/environment.toml`
- Create: `.gitignore`

**Interfaces:**
- Produces: SwiftPM executable product `FindMeGamer` and library `FindMeGamerCore`.
- Produces: `./script/build_and_run.sh [run|--debug|--logs|--telemetry|--verify]`.
- Produces: bundle identifier `com.findmegamer.desktop` and minimum system version `14.0`.

- [ ] **Step 1: Write the failing package smoke test**

```swift
import Testing
@testable import FindMeGamerCore

@Test func coreModuleHasStableProductIdentity() {
    #expect(ProductIdentity.name == "Find Me Gamer")
    #expect(ProductIdentity.bundleIdentifier == "com.findmegamer.desktop")
}
```

- [ ] **Step 2: Run the test and verify the package is absent**

Run: `cd macos && swift test --filter PackageSmokeTests`

Expected: FAIL because `Package.swift` does not exist.

- [ ] **Step 3: Create the three-target package and foreground app scene**

Use `// swift-tools-version: 6.1`, `.macOS(.v14)`, a library target `FindMeGamerCore`, and executable target `FindMeGamer`. The app uses `WindowGroup("Find Me Gamer", id: "main")`. `AppDelegate.applicationDidFinishLaunching` calls `NSApp.setActivationPolicy(.regular)` and `NSApp.activate(ignoringOtherApps: true)`. Define:

```swift
public enum ProductIdentity {
    public static let name = "Find Me Gamer"
    public static let bundleIdentifier = "com.findmegamer.desktop"
}
```

Implement the canonical SwiftPM GUI run script: stop `FindMeGamer`, run `swift build --package-path macos`, stage `dist/FindMeGamer.app`, write an Info.plist containing `FMGAPIBaseURL` from `${SERVICE_BASE_URL:-http://127.0.0.1:8000}`, and open the bundle with `/usr/bin/open -n`. Support all four required flags. The Codex environment contains exactly one Run action pointing to `./script/build_and_run.sh`.

- [ ] **Step 4: Test and verify bundle launch**

Run: `cd macos && swift test && cd .. && ./script/build_and_run.sh --verify`

Expected: Swift tests pass and `pgrep -x FindMeGamer` succeeds.

- [ ] **Step 5: Commit**

```bash
git add macos script/build_and_run.sh .codex/environments/environment.toml .gitignore
git commit -m "build: scaffold macos application"
```

---

### Task 2: Generated OpenAPI target and deterministic schema sync

**Files:**
- Modify: `macos/Package.swift`
- Create: `macos/Sources/FindMeGamerAPI/openapi-generator-config.yaml`
- Create: `macos/Sources/FindMeGamerAPI/openapi.json`
- Create: `macos/Sources/FindMeGamerAPI/APIExports.swift`
- Create: `script/sync_openapi.sh`
- Create: `macos/Tests/FindMeGamerCoreTests/OpenAPIContractTests.swift`

**Interfaces:**
- Produces: generated `Client`, `Operations`, and `Components` in target `FindMeGamerAPI`.
- Produces: `./script/sync_openapi.sh` that copies and verifies `backend/openapi.json`.

- [ ] **Step 1: Write a failing generated-contract test**

```swift
import Testing
import FindMeGamerAPI

@Test func generatedClientIncludesCoreOperations() {
    let names = GeneratedOperationNames.all
    #expect(names.contains("validateSession"))
    #expect(names.contains("createAnalysisJob"))
    #expect(names.contains("createMatch"))
    #expect(names.contains("createSendBatch"))
}
```

- [ ] **Step 2: Run the test and verify the API target is missing**

Run: `cd macos && swift test --filter OpenAPIContractTests`

Expected: FAIL because `FindMeGamerAPI` does not exist.

- [ ] **Step 3: Add Apple packages and generator configuration**

Pin package lower bounds to `swift-openapi-generator` 1.13.0, `swift-openapi-runtime` 1.12.0, and `swift-openapi-urlsession` 1.3.0. Configure:

```yaml
generate:
  - types
  - client
accessModifier: public
```

The sync script runs the backend export command, copies `backend/openapi.json` to `macos/Sources/FindMeGamerAPI/openapi.json`, and then runs `swift build --package-path macos --target FindMeGamerAPI`. `GeneratedOperationNames` is an app-owned constant generated from the approved operation list, so the test detects accidental route deletion without coupling Views to generated symbols.

- [ ] **Step 4: Sync and build generated code**

Run: `./script/sync_openapi.sh && cd macos && swift test --filter OpenAPIContractTests`

Expected: schema generation and test pass.

- [ ] **Step 5: Commit**

```bash
git add macos/Package.swift macos/Sources/FindMeGamerAPI macos/Tests/FindMeGamerCoreTests/OpenAPIContractTests.swift script/sync_openapi.sh
git commit -m "build: generate swift api client"
```

---

### Task 3: Domain models, generated-type mapping, and API service protocol

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Models/CommonModels.swift`
- Create: `macos/Sources/FindMeGamerCore/Models/ProfileModels.swift`
- Create: `macos/Sources/FindMeGamerCore/Models/JobModels.swift`
- Create: `macos/Sources/FindMeGamerCore/Models/MatchModels.swift`
- Create: `macos/Sources/FindMeGamerCore/Models/OutreachModels.swift`
- Create: `macos/Sources/FindMeGamerCore/Models/SettingsModels.swift`
- Create: `macos/Sources/FindMeGamerCore/Services/APIService.swift`
- Create: `macos/Sources/FindMeGamerCore/Services/OpenAPIService.swift`
- Create: `macos/Sources/FindMeGamerCore/Services/WorkspaceAuthMiddleware.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/DomainMappingTests.swift`

**Interfaces:**
- Produces: `protocol APIService: Sendable` with async methods for every approved resource.
- Produces: domain types `GameProfile`, `CreatorProfile`, `AnalysisJob`, `MatchTask`, `MatchResult`, `OutreachCampaign`, `OutreachTemplate`, and `SharedSettings`.
- Produces: `OpenAPIService(baseURL:keyProvider:)` implementing `APIService`.

- [ ] **Step 1: Write failing mapping and score-absence tests**

```swift
@Test func mapsCreatorCardWithoutGeneratedTypesEscaping() throws {
    let card = try DomainMapper.creatorCard(from: Fixtures.creatorCardComponent)
    #expect(card.channelName == "Alpha Plays")
    #expect(card.contactAvailability == .manual)
}

@Test func matchResultHasNoNumericScoreSurface() {
    let properties = Mirror(reflecting: Fixtures.matchResultItem).children.compactMap(\.label)
    #expect(!properties.contains("score"))
    #expect(!properties.contains("rank"))
    #expect(!properties.contains("backendOrder"))
}
```

- [ ] **Step 2: Run mapping tests and verify failure**

Run: `cd macos && swift test --filter DomainMappingTests`

Expected: FAIL because domain and service types are missing.

- [ ] **Step 3: Implement Sendable domain contracts and authenticated client**

Use app-owned UUID-backed `Identifiable` structs and enums with English display labels. Model Match results only with group, qualitative label/outcomes, reasons, Creator card, contact availability, and Outreach state. Define the service boundary with these stable method families:

```swift
public protocol APIService: Sendable {
    func validateSession() async throws -> WorkspaceSession
    func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage
    func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws -> AnalysisSubmission
    func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob
    func listProfiles(type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int) async throws -> ProfileCardPage
    func profile(type: ProfileType, id: UUID) async throws -> Profile
    func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws -> ProfileCard
    func updateCreatorManual(id: UUID, email: String?, notes: String) async throws -> CreatorProfile
    func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask
    func listMatches(cursor: String?) async throws -> MatchTaskPage
    func match(id: UUID) async throws -> MatchResult
    func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask
    func listCampaigns(cursor: String?) async throws -> CampaignPage
    func campaign(id: UUID) async throws -> OutreachCampaign
    func listTemplates() async throws -> [OutreachTemplate]
    func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate
    func duplicateTemplate(id: UUID) async throws -> OutreachTemplate
    func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate
    func deleteTemplate(id: UUID) async throws
    func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail
    func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview]
    func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws -> SendBatch
    func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery
    func smtpSettings() async throws -> SMTPSettingsStatus
    func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus
    func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws -> ConnectionTestResult
    func sendSMTPTest(to email: String) async throws -> ConnectionTestResult
    func sharedSettings() async throws -> SharedSettings
    func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings
    func connection(_ service: ConnectionService) async throws -> ConnectionStatus
    func replaceConnection(_ service: ConnectionService, secret: String) async throws -> ConnectionStatus
    func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult
}
```

`WorkspaceAuthMiddleware` injects `Authorization: Bearer <key>` and `X-Correlation-ID`; mutating service methods accept an explicit idempotency key where required by the backend. Map every non-2xx generated output into `APIError(code:message:retryable:correlationID:)`.

- [ ] **Step 4: Run mapping tests and package build**

Run: `cd macos && swift test --filter DomainMappingTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore macos/Tests/FindMeGamerCoreTests/DomainMappingTests.swift
git commit -m "feat: add macos api domain boundary"
```

---

### Task 4: Keychain, connectivity, and AppSession startup

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Services/KeychainStore.swift`
- Create: `macos/Sources/FindMeGamerCore/Services/ConnectivityMonitor.swift`
- Create: `macos/Sources/FindMeGamerCore/Features/AppSession.swift`
- Create: `macos/Sources/FindMeGamer/Views/WorkspaceAccessView.swift`
- Modify: `macos/Sources/FindMeGamer/App/FindMeGamerApp.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/AppSessionTests.swift`

**Interfaces:**
- Produces: `protocol WorkspaceKeyStore` with `read`, `save`, and `delete`.
- Produces: `@MainActor @Observable final class AppSession` with states `checking`, `needsKey`, `authenticated`, and `offline`.
- Produces: `connect(key:)`, `restore()`, and `disconnectThisMac()`.

- [ ] **Step 1: Write failing startup and disconnect tests**

```swift
@Test @MainActor func missingKeyShowsAccessScreen() async {
    let session = AppSession(apiFactory: fakeAPIFactory(), keyStore: MemoryKeyStore())
    await session.restore()
    #expect(session.state == .needsKey)
}

@Test @MainActor func invalidSavedKeyIsRemoved() async {
    let store = MemoryKeyStore(value: "bad")
    let session = AppSession(apiFactory: rejectingAPIFactory(), keyStore: store)
    await session.restore()
    #expect(store.value == nil)
    #expect(session.state == .needsKey)
}
```

- [ ] **Step 2: Run AppSession tests and verify failure**

Run: `cd macos && swift test --filter AppSessionTests`

Expected: FAIL because the session is absent.

- [ ] **Step 3: Implement Keychain-backed access and observable connectivity**

Use Security framework generic-password entries with service `com.findmegamer.desktop` and account `workspace-access-key`. Read the API base URL from the app bundle's `FMGAPIBaseURL`; fail visibly if invalid. Validate the key before saving. `NWPathMonitor` reports network reachability, while API failures can also transition to offline. Disconnect clears only Keychain and in-memory API services.

- [ ] **Step 4: Run session tests**

Run: `cd macos && swift test --filter AppSessionTests`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Services macos/Sources/FindMeGamerCore/Features/AppSession.swift macos/Sources/FindMeGamer/Views/WorkspaceAccessView.swift macos/Sources/FindMeGamer/App macos/Tests/FindMeGamerCoreTests/AppSessionTests.swift
git commit -m "feat: connect macos app to workspace"
```

---

### Task 5: Root sidebar, independent feature navigation, offline banner, and appearance

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Models/AppDestination.swift`
- Create: `macos/Sources/FindMeGamer/Views/SidebarView.swift`
- Create: `macos/Sources/FindMeGamer/Views/AuthenticatedRootView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Shared/OfflineBanner.swift`
- Create: `macos/Sources/FindMeGamer/Support/AppearancePreferences.swift`
- Modify: `macos/Sources/FindMeGamer/Views/AppRootView.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/AppDestinationTests.swift`

**Interfaces:**
- Produces: destinations `.library`, `.match`, `.outreach`, and `.settings` in that order.
- Produces: `AppearancePreferences` backed by AppStorage keys `appearance-mode` and `font-size`.

- [ ] **Step 1: Write failing navigation-copy tests**

```swift
@Test func sidebarDestinationsAreExactAndOrdered() {
    #expect(AppDestination.allCases.map(\.title) == [
        "Library", "Match", "Outreach Management", "Settings"
    ])
}
```

- [ ] **Step 2: Run the test and verify failure**

Run: `cd macos && swift test --filter AppDestinationTests`

Expected: FAIL because destinations do not exist.

- [ ] **Step 3: Implement the native two-column shell**

Use `NavigationSplitView` with a flat `.sidebar` List, one SF Symbol and one title per row, and `@SceneStorage("sidebar-selection")`; default a missing selection to Library. Keep one `NavigationStack` path per feature in scene-owned state. Do not paint an opaque custom sidebar background. Place `OfflineBanner` above detail content and disable environment-scoped write actions while offline. Apply `.preferredColorScheme` and one of five `DynamicTypeSize` values from Appearance preferences.

- [ ] **Step 4: Build and verify destination tests**

Run: `cd macos && swift test --filter AppDestinationTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources macos/Tests/FindMeGamerCoreTests/AppDestinationTests.swift
git commit -m "feat: add native macos workspace shell"
```

---

### Task 6: Shared changed-Job poller

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Services/AppClock.swift`
- Create: `macos/Sources/FindMeGamerCore/Services/JobPoller.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/Support/ManualClock.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/JobPollerTests.swift`

**Interfaces:**
- Produces: `actor JobPoller` with `start()`, `stop()`, `refreshNow()`, and `events: AsyncStream<JobChangeBatch>`.
- Produces: `protocol AppClock: Sendable { func sleep(for duration: Duration) async throws }`, implemented by `ContinuousAppClock` and test `ManualClock`.
- Consumes: `APIService.listJobs(changedAfter:status:)`.

- [ ] **Step 1: Write failing active/idle polling tests with a ManualClock**

```swift
@Test func pollerUsesThreeSecondsOnlyWhileJobsAreActive() async {
    let api = FakeAPI(jobPages: [.withRunningJob, .allSucceeded])
    let clock = ManualClock()
    let poller = JobPoller(api: api, clock: clock)
    await poller.start()
    await clock.advance(by: .seconds(3))
    #expect(await api.listJobsCalls == 2)
    await clock.advance(by: .seconds(30))
    #expect(await api.listJobsCalls == 2)
}
```

- [ ] **Step 2: Run poller tests and verify failure**

Run: `cd macos && swift test --filter JobPollerTests`

Expected: FAIL because `JobPoller` is absent.

- [ ] **Step 3: Implement cancellable batched polling**

Store the opaque cursor, issue one list call for all changed Jobs, and emit affected Profile/Match/Campaign IDs. Sleep three seconds only when the most recent batch contains queued/running Jobs. `refreshNow()` cancels the wait and polls immediately for app activation/manual Refresh. Make stream termination cancel the task; never retain a View.

- [ ] **Step 4: Run poller tests**

Run: `cd macos && swift test --filter JobPollerTests`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Services/AppClock.swift macos/Sources/FindMeGamerCore/Services/JobPoller.swift macos/Tests/FindMeGamerCoreTests/Support/ManualClock.swift macos/Tests/FindMeGamerCoreTests/JobPollerTests.swift
git commit -m "feat: poll shared cloud jobs"
```

---

### Task 7: Library feature model with debounce, paging, and optimistic favorites

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Features/LibraryModel.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/LibraryModelTests.swift`

**Interfaces:**
- Produces: `@MainActor @Observable final class LibraryModel`.
- Produces: `selectType`, `setOnlyCollection`, `setSearch`, `loadFirstPage`, `loadNextPage`, `toggleFavorite`, and `consume(jobBatch:)`.

- [ ] **Step 1: Write failing debounce and rollback tests**

```swift
@Test @MainActor func searchDebouncesAndKeepsFilters() async {
    let api = FakeAPI()
    let clock = ManualClock()
    let model = LibraryModel(api: api, clock: clock)
    model.onlyCollection = true
    model.setSearch("str")
    model.setSearch("strategy")
    await clock.advance(by: .milliseconds(300))
    #expect(await api.lastProfileQuery == .init(type: .creator, query: "strategy", onlyCollection: true))
}

@Test @MainActor func failedFavoriteRollsBack() async {
    let model = LibraryModel(api: failingFavoriteAPI(), seededWith: [.creator(favorite: false)])
    await model.toggleFavorite(id: model.items[0].id)
    #expect(model.items[0].isFavorite == false)
    #expect(model.error?.message == "Could not update favorite.")
}
```

- [ ] **Step 2: Run Library model tests and verify failure**

Run: `cd macos && swift test --filter LibraryModelTests`

Expected: FAIL because `LibraryModel` is absent.

- [ ] **Step 3: Implement per-type state and stable paging**

Maintain separate Game and Creator item arrays, cursor, query, selection, and loading state so switching preserves controls. Debounce search at 300 ms with task cancellation. Ignore stale responses using a request generation token. Optimistically flip Favorite, call the API, and restore the original value on failure. When a completed Analysis Job affects the selected type, refresh page one and set `highlightedProfileID` for a short animation.

- [ ] **Step 4: Run Library tests**

Run: `cd macos && swift test --filter LibraryModelTests`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Features/LibraryModel.swift macos/Tests/FindMeGamerCoreTests/LibraryModelTests.swift
git commit -m "feat: manage profile library state"
```

---

### Task 8: Library header, search placement, flat gallery cards, and pagination

**Files:**
- Create: `macos/Sources/FindMeGamer/Views/Library/LibraryView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Library/LibraryHeader.swift`
- Create: `macos/Sources/FindMeGamer/Views/Library/GameProfileCard.swift`
- Create: `macos/Sources/FindMeGamer/Views/Library/CreatorProfileCard.swift`
- Create: `macos/Sources/FindMeGamer/Views/Shared/AsyncArtwork.swift`
- Create: `macos/Tests/FindMeGamerUITests/LibraryStructureTests.swift`

**Interfaces:**
- Consumes: `LibraryModel` from Task 7.
- Produces: exact two-row header and adaptive `LazyVGrid`.

- [ ] **Step 1: Write failing structural accessibility tests**

```swift
@Test func libraryControlsHaveStableAccessibilityIdentifiers() {
    #expect(LibraryAccessibility.profileType == "library.profile-type")
    #expect(LibraryAccessibility.onlyCollection == "library.only-collection")
    #expect(LibraryAccessibility.search == "library.search")
    #expect(LibraryAccessibility.analyze == "library.analyze-request")
}
```

- [ ] **Step 2: Run UI structure tests and verify failure**

Run: `cd macos && swift test --filter LibraryStructureTests`

Expected: FAIL because Library views/constants are absent.

- [ ] **Step 3: Build the approved two-row Library surface**

First row contains segmented Game/Creator, checkbox-style Only Collection, flexible space, and Analyze Request with active-Job badge. Second row contains a left-aligned search field capped near 360 points. Use `LazyVGrid(columns: [.init(.adaptive(minimum: 240, maximum: 340))])`; cards use system semantic colors, no glass, and a dedicated Favorite button with a plain style so it never opens the Sheet. `AsyncArtwork` uses a URLSession configured with the system URL cache and keeps no app-owned persistent image database. A bottom sentinel triggers `loadNextPage()` once.

- [ ] **Step 4: Build and run structure tests**

Run: `cd macos && swift test --filter LibraryStructureTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamer/Views/Library macos/Sources/FindMeGamer/Views/Shared/AsyncArtwork.swift macos/Tests/FindMeGamerUITests/LibraryStructureTests.swift
git commit -m "feat: build profile library workspace"
```

---

### Task 9: Analyze Request Inspector and Job status presentation

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Features/AnalyzeRequestModel.swift`
- Create: `macos/Sources/FindMeGamer/Views/Library/AnalyzeRequestInspector.swift`
- Create: `macos/Sources/FindMeGamer/Views/Shared/JobStatusRow.swift`
- Modify: `macos/Sources/FindMeGamer/Views/Library/LibraryView.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/AnalyzeRequestModelTests.swift`

**Interfaces:**
- Produces: `submit()`, `reanalyze(jobOrProfile:)`, `retry(job:)`, and reverse-chronological `jobs`.
- Consumes: JobPoller batches and API Job methods.

- [ ] **Step 1: Write failing validation and cloud-lifetime tests**

```swift
@Test @MainActor func submitRequiresMatchingTargetURL() async {
    let model = AnalyzeRequestModel(api: FakeAPI())
    model.targetType = .game
    model.urlText = "https://youtube.com/@creator"
    await model.submit()
    #expect(model.validationMessage == "Enter a Steam game page URL.")
}

@Test @MainActor func closingInspectorDoesNotCancelSubmittedJob() async {
    let api = FakeAPI()
    let model = AnalyzeRequestModel(api: api)
    await model.submitValidCreator()
    model.inspectorPresented = false
    #expect(await api.cancelCalls == 0)
}
```

- [ ] **Step 2: Run Analyze model tests and verify failure**

Run: `cd macos && swift test --filter AnalyzeRequestModelTests`

Expected: FAIL because model and inspector are absent.

- [ ] **Step 3: Implement Inspector and concise statuses**

Attach `.inspector(isPresented:)` to Library detail. Include segmented Creator/Game, URL field, Submit, and reverse Job history. Map queued/running to `ProgressView`, succeeded to a green status symbol, failed to red; show only `Fetching Data`, `Analyzing`, or `Finalizing`. Existing Profile responses show Open Profile and Re-analyze. Disable writes offline but never tie a cloud Job to Inspector lifetime.

- [ ] **Step 4: Run tests and build**

Run: `cd macos && swift test --filter AnalyzeRequestModelTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Features/AnalyzeRequestModel.swift macos/Sources/FindMeGamer/Views macos/Tests/FindMeGamerCoreTests/AnalyzeRequestModelTests.swift
git commit -m "feat: add analyze request inspector"
```

---

### Task 10: Shared Game and Creator Profile Sheet

**Files:**
- Create: `macos/Sources/FindMeGamer/Views/Profile/ProfileSheet.swift`
- Create: `macos/Sources/FindMeGamer/Views/Profile/ProfileHeader.swift`
- Create: `macos/Sources/FindMeGamer/Views/Profile/GameProfileDetail.swift`
- Create: `macos/Sources/FindMeGamer/Views/Profile/CreatorProfileDetail.swift`
- Create: `macos/Sources/FindMeGamer/Views/Profile/FactSection.swift`
- Create: `macos/Tests/FindMeGamerUITests/ProfileFieldCoverageTests.swift`

**Interfaces:**
- Produces: `ProfileSheet(profile:onFavorite:onReanalyze:onSaveManual:)` reusable from Library and Match.

- [ ] **Step 1: Write failing field-coverage tests**

```swift
@Test func profileSectionsCoverApprovedAnalysis() {
    #expect(Set(GameProfileSection.allCases).isSuperset(of: [.gameplay, .visualStyle, .audience, .contentHooks, .risks]))
    #expect(Set(CreatorProfileSection.allCases).isSuperset(of: [.performance, .content, .audienceInference, .promotionFit, .contact]))
}
```

- [ ] **Step 2: Run field tests and verify failure**

Run: `cd macos && swift test --filter ProfileFieldCoverageTests`

Expected: FAIL because Profile sections are absent.

- [ ] **Step 3: Implement one resizable system Sheet with adaptive detail layout**

The common header shows image, name, source link, Favorite, Re-analyze, Last Analyzed, and Next Re-analysis. Use `ViewThatFits` or container width to switch between two-column and one-column facts. Render factual source data and AI inference in separately labeled sections. Creator contact shows Manual/Discovered source, validation state, editable manual email/notes, and never embeds a Match Brief. Display unavailable fields honestly and hide expired YouTube facts when stale.

- [ ] **Step 4: Run tests and build**

Run: `cd macos && swift test --filter ProfileFieldCoverageTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamer/Views/Profile macos/Tests/FindMeGamerUITests/ProfileFieldCoverageTests.swift
git commit -m "feat: show shared profile details"
```

---

### Task 11: Match feature model, creation, history, and Job updates

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Features/MatchModel.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/MatchModelTests.swift`

**Interfaces:**
- Produces: `@MainActor @Observable final class MatchModel`.
- Produces: `loadGames`, `submit`, `loadHistory`, `openResult`, `retry`, and `consume(jobBatch:)`.

- [ ] **Step 1: Write failing selection and no-result tests**

```swift
@Test @MainActor func submitIsUnavailableUntilGameSelected() {
    let model = MatchModel(api: FakeAPI())
    #expect(model.canSubmit == false)
    model.selectedGame = Fixtures.gameCard
    #expect(model.canSubmit == true)
}

@Test @MainActor func emptySucceededMatchHasClearState() async {
    let model = MatchModel(api: APIWithEmptyMatch())
    await model.openResult(id: Fixtures.emptyMatchID)
    #expect(model.resultState == .empty("No suitable creators found"))
}
```

- [ ] **Step 2: Run Match model tests and verify failure**

Run: `cd macos && swift test --filter MatchModelTests`

Expected: FAIL because `MatchModel` is absent.

- [ ] **Step 3: Implement idempotent creation and stage mapping**

Generate one UUID idempotency key per user action and retain it across network retry. Insert the returned task into reverse-chronological history immediately. Map server stages to Screening, Comparing Creators, and Ranking. A completed Job refreshes only the affected task; a failed task exposes Retry. Preserve backend array order without adding a visible position.

- [ ] **Step 4: Run Match model tests**

Run: `cd macos && swift test --filter MatchModelTests`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Features/MatchModel.swift macos/Tests/FindMeGamerCoreTests/MatchModelTests.swift
git commit -m "feat: manage match workflow state"
```

---

### Task 12: Match Hero, history, result disclosure, and Outreach selection

**Files:**
- Create: `macos/Sources/FindMeGamer/Views/Match/MatchView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Match/MatchHero.swift`
- Create: `macos/Sources/FindMeGamer/Views/Match/MatchHistoryList.swift`
- Create: `macos/Sources/FindMeGamer/Views/Match/MatchResultView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Match/CreatorMatchRow.swift`
- Create: `macos/Sources/FindMeGamer/Views/Match/MatchBriefView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Match/BatchOutreachBar.swift`
- Create: `macos/Tests/FindMeGamerUITests/MatchPresentationTests.swift`

**Interfaces:**
- Consumes: `MatchModel`, Profile Sheet, and Email composer presentation closure.
- Produces: centered Hero and pushed Match Result detail.

- [ ] **Step 1: Write failing copy and score-prohibition tests**

```swift
@Test func matchPresentationUsesQualitativeCopyOnly() {
    #expect(MatchCopy.heroPrefix == "Find me a creator for")
    #expect(MatchCopy.sections == ["Recommended Matches", "Other Matches"])
    #expect(Set(MatchCopy.visibleLabels).isDisjoint(with: ["Score", "Rank", "#1", "Top 1"]))
}
```

- [ ] **Step 2: Run presentation tests and verify failure**

Run: `cd macos && swift test --filter MatchPresentationTests`

Expected: FAIL because Match views/copy are absent.

- [ ] **Step 3: Build progressive Match workspace**

Center `Find me a creator for [Select Game] [Submit]` with generous whitespace; hide Submit until selection. History rows show cover/name/time/stage/status/result count and push successful results. Result detail shows compact Game header, Recommended expanded, Other in a `DisclosureGroup` collapsed, qualitative labels/reasons, and nested `View Match Details`. Creator identity opens the current Profile Sheet. Checkboxes are disabled for missing email or prior send; a previously sent row exposes a deliberate `Resend` action only when the server says it is eligible. The batch bar shows `Send Outreach (N)`. Never render array indices.

- [ ] **Step 4: Run tests and build**

Run: `cd macos && swift test --filter MatchPresentationTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamer/Views/Match macos/Tests/FindMeGamerUITests/MatchPresentationTests.swift
git commit -m "feat: build match workspace"
```

---

### Task 13: Outreach composer with per-Creator preview and send-only overrides

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Features/OutreachComposerModel.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/OutreachComposerSheet.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/RenderedEmailPreview.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/OutreachComposerModelTests.swift`

**Interfaces:**
- Produces: `load(matchID:creatorIDs:)`, `selectTemplate`, `updateOverride`, `refreshPreview`, and `confirmSend`.
- Produces: one system Sheet for individual and batch sends.

- [ ] **Step 1: Write failing confirmation and idempotency tests**

```swift
@Test @MainActor func sendRequiresExplicitFinalConfirmation() async {
    let api = FakeAPI()
    let model = OutreachComposerModel(api: api)
    await model.load(matchID: Fixtures.matchID, creatorIDs: [Fixtures.creatorID])
    #expect(await api.sendBatchCalls == 0)
    await model.confirmSend()
    #expect(await api.sendBatchCalls == 1)
}

@Test @MainActor func editingPreviewDoesNotMutateTemplate() async {
    let model = OutreachComposerModel(api: FakeAPI())
    await model.applySendOnlyBody("Personal note")
    #expect(model.selectedTemplate.body != "Personal note")
}
```

- [ ] **Step 2: Run composer tests and verify failure**

Run: `cd macos && swift test --filter OutreachComposerModelTests`

Expected: FAIL because composer is absent.

- [ ] **Step 3: Implement preview-first composition**

Load Templates and default selection, ask the server for rendered previews, and show recipient tabs when batching. Allow subject/body edits in a send-only draft without updating the Template. Show CTA labels as a locked system-managed preview block. Validate every recipient and duplicate rule before enabling Confirm. Preserve one idempotency UUID through timeout/retry and dismiss only after the batch is accepted.

- [ ] **Step 4: Run composer tests and build**

Run: `cd macos && swift test --filter OutreachComposerModelTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Features/OutreachComposerModel.swift macos/Sources/FindMeGamer/Views/Outreach macos/Tests/FindMeGamerCoreTests/OutreachComposerModelTests.swift
git commit -m "feat: compose match outreach"
```

---

### Task 14: Outreach Management Campaigns and Templates

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Features/OutreachManagementModel.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/OutreachManagementView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/CampaignsView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/CampaignDetailView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/TemplatesView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/TemplateEditor.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/OutreachManagementModelTests.swift`

**Interfaces:**
- Produces: Campaign list/detail loading and Template create/duplicate/edit/default/delete/preview operations.
- Produces: segmented tabs `Campaigns`, `Templates`, and `Email Settings` with Campaigns default.

- [ ] **Step 1: Write failing Campaign and Template state tests**

```swift
@Test @MainActor func campaignsIsDefaultTab() {
    #expect(OutreachManagementModel(api: FakeAPI()).selectedTab == .campaigns)
}

@Test @MainActor func templatePreviewDebouncesEdits() async {
    let api = FakeAPI()
    let clock = ManualClock()
    let model = OutreachManagementModel(api: api, clock: clock)
    model.editTemplateBody("Hello")
    model.editTemplateBody("Hello {{creator_name}}")
    await clock.advance(by: .milliseconds(300))
    #expect(await api.previewCalls == 1)
}
```

- [ ] **Step 2: Run management tests and verify failure**

Run: `cd macos && swift test --filter OutreachManagementModelTests`

Expected: FAIL because management model is absent.

- [ ] **Step 3: Implement Campaign and Template workspaces**

Campaign rows show Game, unique sent Creator count, Accepted, Declined, No Response, Failed, and response rate. Detail shows Send Batches and Deliveries with `Sent`, never Delivered. Template editor has subject, Markdown body, variable insertion Menu, accepted/declined labels, 300 ms live server preview, sample validation, and shared-save warning. Expose create, duplicate, set default, and delete with system confirmation dialogs.

- [ ] **Step 4: Run management tests and build**

Run: `cd macos && swift test --filter OutreachManagementModelTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Features/OutreachManagementModel.swift macos/Sources/FindMeGamer/Views/Outreach macos/Tests/FindMeGamerCoreTests/OutreachManagementModelTests.swift
git commit -m "feat: manage campaigns and templates"
```

---

### Task 15: Email Settings and application Settings workspace

**Files:**
- Create: `macos/Sources/FindMeGamerCore/Features/SettingsModel.swift`
- Create: `macos/Sources/FindMeGamer/Views/Outreach/EmailSettingsView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Settings/SettingsView.swift`
- Create: `macos/Sources/FindMeGamer/Views/Settings/AppearanceSettings.swift`
- Create: `macos/Sources/FindMeGamer/Views/Settings/ConnectionsSettings.swift`
- Create: `macos/Sources/FindMeGamer/Views/Settings/ReanalysisSettings.swift`
- Create: `macos/Sources/FindMeGamer/Views/Settings/WorkspaceSettings.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/SettingsModelTests.swift`

**Interfaces:**
- Produces: local appearance mutation, shared settings draft/save, secret replacement/test, SMTP replacement/test, and disconnect.

- [ ] **Step 1: Write failing interval and secret-redaction tests**

```swift
@Test @MainActor func schedulesCannotBeDisabledOrExceedBounds() {
    let model = SettingsModel(api: FakeAPI())
    model.creatorIntervalDays = 31
    #expect(model.canSaveReanalysis == false)
    #expect(model.hasDisableScheduleControl == false)
}

@Test func connectionStateHasNoSecretField() {
    #expect(Mirror(reflecting: Fixtures.youtubeConnection).children.allSatisfy { $0.label != "secret" })
}
```

- [ ] **Step 2: Run Settings tests and verify failure**

Run: `cd macos && swift test --filter SettingsModelTests`

Expected: FAIL because Settings are absent.

- [ ] **Step 3: Implement the approved Settings surfaces**

Email Settings includes host, port, encryption, username, replacement credential, From Name, Reply-To, rate 1–60, Test Connection, Send Test Email, and last result/time. Main Settings includes System/Light/Dark, five font sizes, Restore Defaults; Steam/YouTube/DeepSeek Configured status, Replace Key, Test; Creator 1–30 and Game 1–90 required intervals with last/next run; server status, read-only API URL, app version, and Disconnect This Mac. Shared saves require explicit Save and a coworker-impact warning.

- [ ] **Step 4: Run Settings tests and build**

Run: `cd macos && swift test --filter SettingsModelTests && swift build`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamerCore/Features/SettingsModel.swift macos/Sources/FindMeGamer/Views/Settings macos/Sources/FindMeGamer/Views/Outreach/EmailSettingsView.swift macos/Tests/FindMeGamerCoreTests/SettingsModelTests.swift
git commit -m "feat: build shared and local settings"
```

---

### Task 16: Official Liquid Glass availability wrappers and standard fallback

**Files:**
- Create: `macos/Sources/FindMeGamer/Support/AdaptiveGlassSurface.swift`
- Modify: `macos/Sources/FindMeGamer/Views/Match/MatchHero.swift`
- Modify: `macos/Sources/FindMeGamer/Views/Match/BatchOutreachBar.swift`
- Modify: `macos/Sources/FindMeGamer/Views/Library/AnalyzeRequestInspector.swift`
- Create: `macos/Tests/FindMeGamerUITests/GlassCompatibilityTests.swift`

**Interfaces:**
- Produces: `AdaptiveGlassSurface<Content>` and `AdaptiveGlassActionGroup<Content>`.
- Guarantees: Apple glass on macOS 26+, system `GroupBox`/standard controls on macOS 14–15.

- [ ] **Step 1: Write failing surface-policy tests**

```swift
@Test func glassPolicyLimitsCustomSurfaces() {
    #expect(GlassSurfaceRole.allCases == [.matchHero, .batchOutreach, .analyzeStatus])
    #expect(!GlassSurfaceRole.allCases.contains(.profileCard))
}
```

- [ ] **Step 2: Run compatibility tests and verify failure**

Run: `cd macos && swift test --filter GlassCompatibilityTests`

Expected: FAIL because adaptive surfaces are absent.

- [ ] **Step 3: Implement SDK-isolated official treatment**

Use the following shape and no custom blur/shader:

```swift
@ViewBuilder
var body: some View {
    if #available(macOS 26.0, *) {
        content
            .padding()
            .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22))
    } else {
        GroupBox { content.padding(4) }
            .groupBoxStyle(.automatic)
    }
}
```

Group nearby custom glass actions in one `GlassEffectContainer` on macOS 26. Keep Toolbar, Sidebar, Inspector, Sheet, Segmented Controls, and ordinary Buttons system-native. Gallery cards receive no glass modifier.

- [ ] **Step 4: Build for deployment floor and current SDK**

Run: `cd macos && swift test --filter GlassCompatibilityTests && swift build -Xswiftc -warnings-as-errors`

Expected: PASS with deployment target macOS 14 and macOS 26 symbols guarded.

- [ ] **Step 5: Commit**

```bash
git add macos/Sources/FindMeGamer/Support/AdaptiveGlassSurface.swift macos/Sources/FindMeGamer/Views macos/Tests/FindMeGamerUITests/GlassCompatibilityTests.swift
git commit -m "feat: adopt native liquid glass conditionally"
```

---

### Task 17: Client integration, offline recovery, and launch verification

**Files:**
- Modify: `macos/Sources/FindMeGamer/App/FindMeGamerApp.swift`
- Modify: `macos/Sources/FindMeGamer/Views/AuthenticatedRootView.swift`
- Create: `macos/Tests/FindMeGamerCoreTests/ClientVerticalSliceTests.swift`
- Create: `macos/Tests/FindMeGamerUITests/EnglishCopyTests.swift`
- Create: `macos/README.md`

**Interfaces:**
- Verifies: one fake-backed Analyze→Library→Match→Compose→Campaign client flow.
- Produces: documented build/run/test commands and local API URL behavior.

- [ ] **Step 1: Write the failing client vertical-slice test**

```swift
@Test @MainActor func clientFlowRefreshesOnlyAffectedFeatures() async {
    let harness = ClientHarness(api: FakeVerticalSliceAPI())
    await harness.connect()
    await harness.analyzeCreator()
    await harness.deliverJobCompletion()
    #expect(harness.library.creators.contains { $0.channelName == "Alpha Plays" })
    await harness.match.submit(game: Fixtures.gameCard)
    await harness.composeAndSendFirstRecommended()
    #expect(harness.outreach.campaigns.first?.sentCreators == 1)
}
```

- [ ] **Step 2: Run the full client test suite and capture initial failures**

Run: `cd macos && swift test`

Expected: FAIL until root wiring and fake-backed feature communication are complete.

- [ ] **Step 3: Wire feature models and lifecycle refresh**

Create all feature models after AppSession authenticates and pass them explicitly to root Views. On first authentication, load Library page one, active Jobs, and shared Settings concurrently. Route JobPoller batches to Library and Match only when their resource IDs are affected. On `scenePhase == .active`, trigger immediate Job and visible-feature refresh. Offline disables write environment actions; reconnection refreshes session and visible data without losing local selection or drafts. Scan user-facing literals so all system UI copy is English.

- [ ] **Step 4: Run all Swift tests and verify launch**

Run: `./script/sync_openapi.sh && cd macos && swift test && cd .. && ./script/build_and_run.sh --verify`

Expected: all tests pass and the staged `.app` process launches.

- [ ] **Step 5: Commit**

```bash
git add macos script
git commit -m "test: verify macos client vertical slice"
```
