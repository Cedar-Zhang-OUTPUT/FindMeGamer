import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized) struct DiscoverModelTests {
  @MainActor @Test func openingCreatedMatchRetainsDiscoverContext() async throws {
    let coordinator = ClientCoordinator(
      api: DemoAPIService(), apiBaseURL: "http://127.0.0.1", appVersion: "test")
    await coordinator.loadInitialData()
    coordinator.discover.selectedGame = coordinator.discover.games.first
    await coordinator.discover.submit()
    coordinator.discover.selectAll()
    let selected = coordinator.discover.selectedIDs
    let recordID = coordinator.discover.record?.id
    await coordinator.discover.submitAnalysis(mode: .analyzeAndMatch)
    let matchID = try #require(coordinator.discover.batches.first?.matchID)
    await coordinator.match.openResult(id: matchID)
    #expect(coordinator.match.selectedMatchID == matchID)
    #expect(coordinator.discover.record?.id == recordID)
    #expect(coordinator.discover.selectedIDs == selected)
    #expect(coordinator.discover.batches.count == 1)
  }
  @MainActor @Test func workspaceStartupOwnsInitialDiscoverLoad() async {
    let coordinator = ClientCoordinator(
      api: DemoAPIService(), apiBaseURL: "http://127.0.0.1", appVersion: "test")
    await coordinator.loadInitialData()
    #expect(coordinator.discover.games.count == 5)
    #expect(coordinator.discover.capabilities.contains { $0.platform == "x" && $0.available })
  }
  @MainActor @Test func selectionsIncludeOffscreenCandidatesAndCancelNeverWrites() async {
    let api = RecordingDiscoverAPI()
    let model = DiscoverModel(api: api)
    await model.open(id: api.record.id)
    model.selectAll()
    #expect(model.selectedIDs == Set(api.record.candidates.map(\.id)))
    model.deselectAll()
    #expect(model.selectedIDs.isEmpty)
    model.selectAll()
    model.presentAnalysisConfirmation()
    model.cancelAnalysisConfirmation()
    #expect(model.selectedIDs.count == 12)
    #expect(await api.batchKeys.isEmpty)
    model.presentConditions()
    model.cancelConditions()
    #expect(await api.createKeys.isEmpty)
  }

  @MainActor @Test func uncertainBatchRetryKeepsPayloadAndKeyAndSuccessfulRowsSurviveErrors() async
  {
    let api = RecordingDiscoverAPI()
    let model = DiscoverModel(api: api, idempotencyKey: { "stable-key" })
    await model.open(id: api.record.id)
    model.selectAll()
    await model.submitAnalysis(mode: .analyzeAndMatch)
    #expect(model.error != nil)
    await model.submitAnalysis(mode: .analyzeAndMatch)
    #expect(await api.batchKeys == ["stable-key", "stable-key"])
    #expect(await api.batchModes == [.analyzeAndMatch, .analyzeAndMatch])
    #expect(model.record?.candidates.count == 12)
    await api.failReads()
    await model.open(id: api.record.id)
    #expect(model.record?.candidates.count == 12)
    #expect(model.selectedIDs.count == 12)
  }

  @MainActor @Test func paginatedGamesRemainSearchableAndConditionsCancelRetainsGame() async {
    let api = RecordingDiscoverAPI()
    let model = DiscoverModel(api: api)
    await model.loadGames()
    #expect(model.games.count == 5)
    model.gameQuery = "Fifth"
    #expect(model.filteredGames.map(\.name) == ["Fifth"])
    model.selectedGame = model.filteredGames.first
    model.presentConditions()
    model.cancelConditions()
    #expect(model.selectedGame?.name == "Fifth")
    #expect(await api.createKeys.isEmpty)
  }
}

actor RecordingDiscoverAPI: DiscoverAPIService {
  nonisolated let record = DiscoverRecord(
    id: UUID(), gameID: UUID(), gameName: "Demo game",
    status: "done", stage: nil,
    candidates: (1...12).map {
      DiscoverCandidate(
        id: UUID(), platform: "youtube", accountID: "creator\($0)",
        name: "Creator \($0)", url: "https://youtube.com/@creator\($0)", inLibrary: false)
    }, issues: [], createdAt: Date())
  var batchKeys: [String] = []
  var batchModes: [DiscoverAnalysisMode] = []
  var createKeys: [String] = []
  var readsFail = false
  func failReads() { readsFail = true }
  func discoverCapabilities() async throws -> [DiscoverCapability] { [] }
  func retryDiscover(id: UUID) async throws -> DiscoverRecord { record }
  func discoverHistory(cursor: String?) async throws -> DiscoverPage {
    .init(items: [], nextCursor: nil)
  }
  func discover(id: UUID) async throws -> DiscoverRecord {
    if readsFail { throw APIError.invalidResponse }
    return record
  }
  func resolveDiscoverGame(url: String) async throws -> DiscoverGame {
    throw APIError.invalidResponse
  }
  func discoverGames(cursor: String?) async throws -> DiscoverGamePage {
    let names = cursor == nil ? ["First", "Second", "Third"] : ["Fourth", "Fifth"]
    return .init(
      items: names.map {
        .init(id: UUID(), name: $0, url: "https://store.steampowered.com/app/1/\($0)")
      }, nextCursor: cursor == nil ? "page2" : nil)
  }
  func createDiscover(game: DiscoverGame, conditions: DiscoverConditions, idempotencyKey: String)
    async throws -> DiscoverRecord
  {
    createKeys.append(idempotencyKey)
    return record
  }
  func discoverBatches(id: UUID) async throws -> [DiscoverBatch] { [] }
  func createDiscoverBatch(
    id: UUID, candidateIDs: [UUID], mode: DiscoverAnalysisMode, idempotencyKey: String
  ) async throws -> DiscoverBatch {
    batchKeys.append(idempotencyKey)
    batchModes.append(mode)
    if batchKeys.count == 1 { throw URLError(.timedOut) }
    return .init(
      id: UUID(), discoverID: id, mode: mode, status: "done", items: [], matchID: nil, error: nil)
  }
}
