import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite(.serialized) struct LibraryStructureTests {
  @Test func libraryContractUsesExactCopyAccessibilityAndDesktopDimensions() {
    #expect(LibraryLayout.headerRowCount == 2)
    #expect(LibraryLayout.searchMaximumWidth == 360)
    #expect(LibraryLayout.gridMinimumWidth == 240)
    #expect(LibraryLayout.gridMaximumWidth == 340)
    #expect(LibraryLayout.profileTypes == [.game, .creator])
    #expect(LibraryCopy.searchPlaceholder == "Search Profiles…")
    #expect(LibraryCopy.onlyCollection == "Favorites")
    #expect(LibraryCopy.analyzeRequest == "Analyze Profile")
    #expect(LibraryCopy.empty == "No profiles found.")
    #expect(LibraryAccessibility.profileType == "library.profile-type")
    #expect(LibraryAccessibility.onlyCollection == "library.only-collection")
    #expect(LibraryAccessibility.search == "library.search")
    #expect(LibraryAccessibility.analyzeRequest == "library.analyze-request")
    #expect(LibraryAccessibility.grid == "library.grid")
  }

  @Test func activeAnalysisBadgeHidesNonpositiveCountsAndShowsPositiveCount() {
    #expect(LibraryBadge.visibleCount(for: -1) == nil)
    #expect(LibraryBadge.visibleCount(for: 0) == nil)
    #expect(LibraryBadge.visibleCount(for: 3) == 3)
  }

  @Test func cardPresentationsExtractOnlyApprovedPublicSummaryFields() {
    let gameID = UUID(uuidString: "10000000-0000-4000-8000-000000000001")!
    let game = FindMeGamerCore.GameProfileCard(
      id: gameID,
      name: "Signal Garden",
      steamAppID: "730",
      canonicalURL: "https://store.steampowered.com/app/730",
      favorite: true,
      currentFacts: [
        "short_description": .string("Build a cooperative signal network."),
        "genres": .array([.string("Strategy"), .string("Co-op"), .string("Puzzle")]),
        "cover_image_url": .string("https://cdn.example.test/game.jpg"),
        "hidden_rank": .integer(1),
      ],
      brief: [:],
      sourceStatus: [:],
      lastAnalyzedAt: nil,
      nextAnalysisAt: nil)

    let creatorID = UUID(uuidString: "20000000-0000-4000-8000-000000000001")!
    let creator = FindMeGamerCore.CreatorProfileCard(
      id: creatorID,
      name: "Tactical Cedar",
      youtubeChannelID: "UC-cedar",
      canonicalURL: "https://youtube.com/@tacticalcedar",
      favorite: false,
      currentFacts: [
        "avatar_url": .string("http://images.example.test/avatar.png"),
        "subscriber_count": .integer(125_000),
        "score": .number(0.99),
      ],
      brief: [
        "performance_context": .object(["value": .string("Consistent recent views")]),
        "content_focus": .object([
          "values": .array([.string("Strategy"), .string("Indie"), .string("Reviews")])
        ]),
      ],
      sourceStatus: [:],
      lastAnalyzedAt: nil,
      nextAnalysisAt: nil,
      contact: CreatorContact(
        email: "creator@example.test", availability: .discovered, source: "channel_about",
        sourceURL: nil, validationState: "valid"))

    let gamePresentation = GameCardPresentation(card: game)
    #expect(gamePresentation.name == "Signal Garden")
    #expect(gamePresentation.summary == "Build a cooperative signal network.")
    #expect(gamePresentation.tags == ["Strategy", "Co-op", "Puzzle"])
    #expect(gamePresentation.artworkURL?.absoluteString == "https://cdn.example.test/game.jpg")
    #expect(gamePresentation.isFavorite)

    let creatorPresentation = CreatorCardPresentation(card: creator)
    #expect(creatorPresentation.name == "Tactical Cedar")
    #expect(creatorPresentation.subscriberCount == 125_000)
    #expect(creatorPresentation.performanceSummary == "Consistent recent views")
    #expect(creatorPresentation.tags == ["Strategy", "Indie", "Reviews"])
    #expect(
      creatorPresentation.artworkURL?.absoluteString == "http://images.example.test/avatar.png")
    #expect(creatorPresentation.contactAvailability == "Discovered")
    #expect(!creatorPresentation.isFavorite)
  }

  @Test func wrongShapesAndInternalFieldsProduceUnavailablePresentation() {
    let game = FindMeGamerCore.GameProfileCard(
      id: UUID(), name: "Safe Game", steamAppID: "1", canonicalURL: "https://game.test",
      favorite: false,
      currentFacts: [
        "short_description": .boolean(true),
        "genres": .object(["rank": .string("First")]),
        "cover_image_url": .string("javascript:alert(1)"),
      ],
      brief: ["hidden_rank": .object(["value": .string("Do not show")])],
      sourceStatus: [:], lastAnalyzedAt: nil, nextAnalysisAt: nil)
    let creator = FindMeGamerCore.CreatorProfileCard(
      id: UUID(), name: "Safe Creator", youtubeChannelID: "UC-safe",
      canonicalURL: "https://youtube.com/@safe", favorite: false,
      currentFacts: [
        "subscriber_count": .string("secret count"),
        "avatar_url": .string("data:image/png;base64,AAAA"),
      ],
      brief: [
        "performance_context": .object(["reason": .string("Private")]),
        "content_focus": .object(["rank": .array([.string("Top")])]),
      ],
      sourceStatus: [:], lastAnalyzedAt: nil, nextAnalysisAt: nil, contact: nil)

    let gamePresentation = GameCardPresentation(card: game)
    #expect(gamePresentation.summary == nil)
    #expect(gamePresentation.tags.isEmpty)
    #expect(gamePresentation.artworkURL == nil)

    let creatorPresentation = CreatorCardPresentation(card: creator)
    #expect(creatorPresentation.subscriberCount == nil)
    #expect(creatorPresentation.performanceSummary == nil)
    #expect(creatorPresentation.tags.isEmpty)
    #expect(creatorPresentation.artworkURL == nil)
    #expect(creatorPresentation.contactAvailability == "Unavailable")
  }

  @Test func artworkPolicyAcceptsOnlyAbsoluteWebURLsAndUsesSystemCache() {
    #expect(ArtworkURLPolicy.validated(URL(string: "https://cdn.example.test/a.png")) != nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "http://images.example.test/a.png")) != nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "file:///tmp/a.png")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "data:image/png;base64,AAAA")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "javascript:alert(1)")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "/relative/a.png")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "https:///hostless.png")) == nil)

    let configuration = ArtworkLoader.makeConfiguration()
    #expect(configuration.urlCache === URLCache.shared)
    #expect(configuration.requestCachePolicy == .useProtocolCachePolicy)
  }

  @MainActor
  @Test func removingLastCollectionItemKeepsHostUntilSameCursorReplacement() async {
    let firstID = UUID(uuidString: "30000000-0000-4000-8000-000000000001")!
    let secondID = UUID(uuidString: "30000000-0000-4000-8000-000000000002")!
    let heldPage = PaginationPageGate()
    let first = paginationGame(firstID, name: "First", favorite: true)
    let unfavorite = paginationGame(firstID, name: "First")
    let second = paginationGame(secondID, name: "Second", favorite: true)
    let api = PaginationAPI(
      outcomes: [
        .page(ProfileCardPage(items: [first], nextCursor: "cursor-a")),
        .gated(heldPage),
        .page(ProfileCardPage(items: [second], nextCursor: "cursor-b")),
      ],
      favoriteResult: unfavorite)
    let model = LibraryModel(api: api)
    let pagination = LibraryPaginationCoordinator()

    model.selectType(.game)
    model.setOnlyCollection(true)
    #expect(await paginationEventually { await api.listCallCount == 1 })
    #expect(await paginationEventually { !model.isLoadingFirstPage })
    let request = paginationRequest(model)
    let firstTaskID = pagination.taskID(for: request)
    let oldLoad = Task { @MainActor in
      await pagination.run(
        taskID: firstTaskID,
        load: { await model.loadNextPage() },
        current: { paginationObservation(model) })
    }
    await heldPage.waitUntilEntered()

    await model.toggleFavorite(id: firstID)
    pagination.observe(paginationObservation(model))
    #expect(model.items.isEmpty)
    #expect(model.nextCursor == "cursor-a")
    #expect(model.canLoadNextPage)
    #expect(
      LibraryContentPolicy.presentation(
        itemCount: model.items.count,
        isLoadingFirstPage: model.isLoadingFirstPage,
        hasError: model.error != nil,
        hasNextCursor: model.nextCursor != nil,
        isLoadingNextPage: model.isLoadingNextPage,
        keepsPaginationHost: pagination.keepsPaginationHost)
        == .scrollable(showEmptyState: true))
    #expect(await api.listCallCount == 2)
    #expect(await api.maximumConcurrentListCalls == 1)

    heldPage.resume(ProfileCardPage(items: [], nextCursor: "stale-cursor"))
    await oldLoad.value
    #expect(pagination.revision == 1)
    #expect(await api.listCallCount == 2)

    let replacementRequest = paginationRequest(model)
    await pagination.run(
      taskID: pagination.taskID(for: replacementRequest),
      load: { await model.loadNextPage() },
      current: { paginationObservation(model) })

    #expect(await api.listCallCount == 3)
    #expect(await api.maximumConcurrentListCalls == 1)
    #expect(model.items.map(\.id) == [secondID])
    #expect(model.nextCursor == "cursor-b")
  }

  @MainActor
  @Test func failedNextPageWaitsForManualRetryAndPageOneCanRearmSameCursor() async {
    let firstID = UUID(uuidString: "40000000-0000-4000-8000-000000000001")!
    let secondID = UUID(uuidString: "40000000-0000-4000-8000-000000000002")!
    let api = PaginationAPI(
      outcomes: [
        .page(
          ProfileCardPage(
            items: [paginationGame(firstID, name: "First")], nextCursor: "cursor-a")),
        .failure(APIError(code: "offline", message: "offline", retryable: true)),
        .page(
          ProfileCardPage(items: [paginationGame(secondID, name: "Second")], nextCursor: nil)),
      ])
    let model = LibraryModel(api: api)
    let pagination = LibraryPaginationCoordinator()

    model.selectType(.game)
    #expect(await paginationEventually { await api.listCallCount == 1 && !model.isLoadingFirstPage })
    let request = paginationRequest(model)
    await pagination.run(
      taskID: pagination.taskID(for: request),
      load: { await model.loadNextPage() },
      current: { paginationObservation(model) })

    #expect(await api.listCallCount == 2)
    #expect(model.error?.message == "Could not load profiles.")
    #expect(
      LibraryRetryPolicy.action(failedRequest: pagination.failedRequest, current: request)
        == .nextPage)
    for _ in 0..<20 { await Task.yield() }
    #expect(await api.listCallCount == 2)

    pagination.retry(request)
    await pagination.run(
      taskID: pagination.taskID(for: request),
      load: { await model.loadNextPage() },
      current: { paginationObservation(model) })
    #expect(await api.listCallCount == 3)
    #expect(model.items.map(\.id) == [firstID, secondID])
    #expect(model.error == nil)
    #expect(
      LibraryRetryPolicy.action(failedRequest: pagination.failedRequest, current: nil)
        == .firstPage)

    let sameCursor = LibraryPaginationRequest(
      profileType: .game, query: "", onlyCollection: false, cursor: "cursor-a")
    let previousRevision = pagination.revision
    pagination.observe(
      LibraryPaginationObservation(
        request: sameCursor, canLoadNextPage: false, isLoadingFirstPage: true,
        isLoadingNextPage: false, hasError: false))
    pagination.observe(
      LibraryPaginationObservation(
        request: sameCursor, canLoadNextPage: true, isLoadingFirstPage: false,
        isLoadingNextPage: false, hasError: false))
    #expect(pagination.revision == previousRevision + 1)

    let changedCriteria = LibraryPaginationRequest(
      profileType: .game, query: "new", onlyCollection: false, cursor: "cursor-a")
    #expect(pagination.taskID(for: changedCriteria) != pagination.taskID(for: sameCursor))
  }
}

private enum PaginationListOutcome: Sendable {
  case page(ProfileCardPage)
  case failure(APIError)
  case gated(PaginationPageGate)
}

private actor PaginationPageGate {
  private var entered = false
  private var continuation: CheckedContinuation<ProfileCardPage, Never>?

  func wait() async -> ProfileCardPage {
    entered = true
    return await withCheckedContinuation { continuation = $0 }
  }

  func waitUntilEntered() async {
    while !entered { await Task.yield() }
  }

  nonisolated func resume(_ page: ProfileCardPage) {
    Task { await resumeOnActor(page) }
  }

  private func resumeOnActor(_ page: ProfileCardPage) {
    continuation?.resume(returning: page)
    continuation = nil
  }
}

private actor PaginationAPI: APIService {
  private var outcomes: [PaginationListOutcome]
  private let favoriteResult: ProfileCard?
  private var activeListCalls = 0
  private(set) var maximumConcurrentListCalls = 0
  private(set) var listCallCount = 0

  func listCreatorPage(query: String, onlyCollection: Bool, page: Int) async throws -> ProfileCardPage {
    var result = try await listProfiles(type: .creator, query: query,
      onlyCollection: onlyCollection, cursor: page == 1 ? nil : String(page), limit: 20)
    result.page = page
    result.totalPages = result.nextCursor == nil ? page : page + 1
    return result
  }

  init(outcomes: [PaginationListOutcome], favoriteResult: ProfileCard? = nil) {
    self.outcomes = outcomes
    self.favoriteResult = favoriteResult
  }

  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    listCallCount += 1
    activeListCalls += 1
    maximumConcurrentListCalls = max(maximumConcurrentListCalls, activeListCalls)
    defer { activeListCalls -= 1 }
    switch outcomes.removeFirst() {
    case .page(let page): return page
    case .failure(let error): throw error
    case .gated(let gate): return await gate.wait()
    }
  }

  func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws -> ProfileCard {
    guard let favoriteResult else { fatalError("Unexpected Favorite request") }
    return favoriteResult
  }
}

extension APIService {
  fileprivate func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  fileprivate func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage
  {
    fatalError("unused")
  }
  fileprivate func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String)
    async throws
    -> AnalysisSubmission
  { fatalError("unused") }
  fileprivate func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    fatalError("unused")
  }
  fileprivate func profile(type: ProfileType, id: UUID) async throws -> Profile {
    fatalError("unused")
  }
  fileprivate func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  {
    fatalError("unused")
  }
  fileprivate func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func listMatches(cursor: String?) async throws -> MatchTaskPage {
    fatalError("unused")
  }
  fileprivate func match(id: UUID) async throws -> MatchResult { fatalError("unused") }
  fileprivate func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func listCampaigns(cursor: String?) async throws -> CampaignPage {
    fatalError("unused")
  }
  fileprivate func campaign(id: UUID) async throws -> OutreachCampaign { fatalError("unused") }
  fileprivate func listTemplates() async throws -> [OutreachTemplate] { fatalError("unused") }
  fileprivate func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func duplicateTemplate(id: UUID) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func deleteTemplate(id: UUID) async throws { fatalError("unused") }
  fileprivate func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    fatalError("unused")
  }
  fileprivate func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    fatalError("unused")
  }
  fileprivate func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  {
    fatalError("unused")
  }
  fileprivate func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
  fileprivate func smtpSettings() async throws -> SMTPSettingsStatus { fatalError("unused") }
  fileprivate func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    fatalError("unused")
  }
  fileprivate func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws
    -> ConnectionTestResult
  {
    fatalError("unused")
  }
  fileprivate func sendSMTPTest(to email: String) async throws -> ConnectionTestResult {
    fatalError("unused")
  }
  fileprivate func sharedSettings() async throws -> SharedSettings { fatalError("unused") }
  fileprivate func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    fatalError("unused")
  }
  fileprivate func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    fatalError("unused")
  }
  fileprivate func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  { fatalError("unused") }
  fileprivate func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult
  {
    fatalError("unused")
  }
}

@MainActor
private func paginationRequest(_ model: LibraryModel) -> LibraryPaginationRequest {
  LibraryPaginationRequest(
    profileType: model.selectedType, query: model.query, onlyCollection: model.onlyCollection,
    cursor: model.nextCursor!)
}

@MainActor
private func paginationObservation(_ model: LibraryModel) -> LibraryPaginationObservation {
  LibraryPaginationObservation(
    request: model.nextCursor.map {
      LibraryPaginationRequest(
        profileType: model.selectedType, query: model.query,
        onlyCollection: model.onlyCollection, cursor: $0)
    },
    canLoadNextPage: model.canLoadNextPage, isLoadingFirstPage: model.isLoadingFirstPage,
    isLoadingNextPage: model.isLoadingNextPage, hasError: model.error != nil)
}

private func paginationGame(
  _ id: UUID, name: String, favorite: Bool = false
) -> ProfileCard {
  .game(
    GameProfileCard(
      id: id, name: name, steamAppID: "730",
      canonicalURL: "https://store.steampowered.com/app/730", favorite: favorite,
      currentFacts: [:], brief: [:], sourceStatus: [:], lastAnalyzedAt: nil,
      nextAnalysisAt: nil))
}

@MainActor
private func paginationEventually(_ predicate: @MainActor () async -> Bool) async -> Bool {
  for _ in 0..<300 {
    if await predicate() { return true }
    await Task.yield()
  }
  return await predicate()
}
