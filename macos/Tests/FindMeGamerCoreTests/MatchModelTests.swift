import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct MatchModelTests {
  @MainActor
  @Test func gameLoadingDrainsCanonicalPagesAndCommitsAtomically() async {
    let first = gameCard(id: id(1), name: "First", favorite: false)
    let refreshed = gameCard(id: id(1), name: "First Canonical", favorite: true)
    let second = gameCard(id: id(2), name: "Second", favorite: false)
    let api = MatchAPI(
      profileOutcomes: [
        .value(ProfileCardPage(items: [.game(first)], nextCursor: nil)),
        .value(ProfileCardPage(items: [.game(refreshed)], nextCursor: "opaque +/ cursor")),
        .value(ProfileCardPage(items: [.game(refreshed), .game(second)], nextCursor: nil)),
        .value(ProfileCardPage(items: [.game(second)], nextCursor: "later-page")),
        .failure(APIError(code: "page_failed", message: "Unsafe detail", retryable: true)),
      ])
    let model = MatchModel(api: api)

    #expect(!model.canSubmit)
    await model.loadGames()
    model.selectedGame = first
    #expect(model.canSubmit)

    await model.loadGames()
    #expect(model.games == [refreshed, second])
    #expect(model.selectedGame == refreshed)
    #expect(
      await api.profileCalls == [
        .init(type: .game, query: "", onlyCollection: false, cursor: nil, limit: 100),
        .init(type: .game, query: "", onlyCollection: false, cursor: nil, limit: 100),
        .init(
          type: .game, query: "", onlyCollection: false, cursor: "opaque +/ cursor", limit: 100),
      ])

    let committedGames = model.games
    let committedSelection = model.selectedGame
    await model.loadGames()
    #expect(model.games == committedGames)
    #expect(model.selectedGame == committedSelection)
    #expect(model.gamesError == "Could not load Game Profiles.")
    #expect(await api.profileCalls.last?.cursor == "later-page")
  }

  @MainActor
  @Test func heldGameLoadSuppressesOverlapAndClearsMissingSelectionOnSuccess() async {
    let gate = MatchGate<ProfileCardPage>()
    let game = gameCard(id: id(3), name: "Selected", favorite: false)
    let api = MatchAPI(
      profileOutcomes: [
        .value(ProfileCardPage(items: [.game(game)], nextCursor: nil)),
        .gated(gate),
      ])
    let model = MatchModel(api: api)
    await model.loadGames()
    model.selectedGame = game

    let load = Task { await model.loadGames() }
    #expect(await gate.waitUntilEntered())
    #expect(model.isLoadingGames)
    await model.loadGames()
    #expect(await api.profileCalls.count == 2)
    gate.resume(.success(ProfileCardPage(items: [], nextCursor: nil)))
    await load.value

    #expect(model.games.isEmpty)
    #expect(model.selectedGame == nil)
    #expect(!model.isLoadingGames)
  }

  @MainActor
  @Test func historyPagingSortsDeduplicatesAndCannotEraseConcurrentSubmit() async {
    let older = matchTask(id: id(10), gameID: id(1), created: 10, updated: 10)
    let newer = matchTask(id: id(11), gameID: id(2), created: 20, updated: 20)
    let newerCanonical = matchTask(
      id: id(11), gameID: id(2), status: .running, created: 20, updated: 21)
    let created = matchTask(id: id(12), gameID: id(3), created: 30, updated: 30)
    let historyGate = MatchGate<MatchTaskPage>()
    let wake = MatchWakeProbe()
    let api = MatchAPI(
      historyOutcomes: [
        .value(MatchTaskPage(items: [older, newer], cursor: "history cursor +/", hasMore: true)),
        .value(MatchTaskPage(items: [newerCanonical], cursor: nil, hasMore: false)),
        .gated(historyGate),
        .value(MatchTaskPage(items: [older], cursor: "failure-page", hasMore: true)),
        .failure(APIError(code: "history_failed", message: "Unsafe detail", retryable: true)),
      ],
      createOutcomes: [.value(created)])
    let model = MatchModel(
      api: api, idempotencyKey: MatchKeySequence.one.provider,
      onJobActivity: { await wake.record() })

    await model.loadHistory()
    #expect(model.tasks == [newerCanonical, older])
    #expect(await api.historyCalls == [nil, "history cursor +/"])

    let heldHistory = Task { await model.loadHistory() }
    #expect(await historyGate.waitUntilEntered())
    model.selectedGame = gameCard(id: id(3), name: "Third", favorite: false)
    await model.submit()
    historyGate.resume(
      .success(MatchTaskPage(items: [older, newer], cursor: nil, hasMore: false)))
    await heldHistory.value
    #expect(model.tasks.map(\.id) == [created.id, newer.id, older.id])
    #expect(model.tasks.first == created)
    #expect(await wake.count == 1)

    let committed = model.tasks
    await model.loadHistory()
    #expect(model.tasks == committed)
    #expect(model.historyError == "Could not load Match history.")
    #expect(await api.historyCalls.suffix(2) == [nil, "failure-page"])
  }

  @MainActor
  @Test func submitSingleFlightsAndReusesOnlyTheAmbiguousGameKey() async {
    let gameA = gameCard(id: id(20), name: "A", favorite: false)
    let gameB = gameCard(id: id(21), name: "B", favorite: false)
    let taskA = matchTask(id: id(22), gameID: gameA.id, created: 22, updated: 22)
    let taskB = matchTask(id: id(23), gameID: gameB.id, created: 23, updated: 23)
    let gate = MatchGate<MatchTask>()
    let wake = MatchWakeProbe()
    let keys = MatchKeySequence.two
    let api = MatchAPI(
      createOutcomes: [
        .failure(APIError(code: "lost_response", message: "Try again.", retryable: true)),
        .gated(gate),
        .failure(APIError(code: "lost_response", message: "Try again.", retryable: true)),
        .value(taskB),
      ])
    let model = MatchModel(
      api: api, idempotencyKey: keys.provider, onJobActivity: { await wake.record() })

    await model.submit()
    #expect(await api.createCalls.isEmpty)

    model.selectedGame = gameA
    await model.submit()
    #expect(model.actionError == "Try again.")
    #expect(await api.createCalls.map(\.key) == [keys.values[0]])

    let retry = Task { await model.submit() }
    #expect(await gate.waitUntilEntered())
    #expect(!model.canSubmit)
    await model.submit()
    #expect(await api.createCalls.count == 2)
    gate.resume(.success(taskA))
    await retry.value
    #expect(model.tasks.contains(taskA))
    #expect(await api.createCalls.map(\.key) == [keys.values[0], keys.values[0]])

    model.selectedGame = gameB
    await model.submit()
    await model.submit()
    #expect(
      await api.createCalls.map(\.key) == [
        keys.values[0], keys.values[0], keys.values[1], keys.values[1],
      ])
    #expect(await api.createCalls.map(\.gameID) == [gameA.id, gameA.id, gameB.id, gameB.id])
    #expect(model.tasks.first == taskB)
    #expect(await wake.count == 2)
  }

  @MainActor
  @Test func jobBatchesUpdateActiveTasksAndTargetEachTerminalOrUnknownIDOnce() async {
    let gameID = id(30)
    let active = matchTask(
      id: id(31), gameID: gameID, status: .queued, created: 31, updated: 31)
    let terminalResult = matchResult(
      id: active.id, gameID: gameID, status: .succeeded, state: .available,
      recommended: [candidate(id: id(301), name: "First"), candidate(id: id(302), name: "Second")],
      other: [candidate(id: id(303), name: "Other")], updated: 35)
    let unknownResult = matchResult(
      id: id(32), gameID: id(33), status: .failed, state: .pending,
      recommended: [], other: [], updated: 36)
    let api = MatchAPI(
      historyOutcomes: [.value(MatchTaskPage(items: [active], cursor: nil, hasMore: false))],
      matchOutcomes: [.value(terminalResult), .value(unknownResult)])
    let model = MatchModel(api: api)
    await model.loadHistory()

    let running = changedTask(
      id: active.id, gameID: gameID, status: .running, stage: .pairwise, updated: 32)
    let stale = changedTask(
      id: active.id, gameID: gameID, status: .queued, stage: .screening, updated: 30)
    await model.consume(
      jobBatch: batch([
        .analysis(analysisJob(id: id(399))), .match(stale), .match(running),
      ]))
    #expect(model.tasks.first?.status == .running)
    #expect(model.tasks.first?.stage == .pairwise)
    #expect(await api.matchCalls.isEmpty)
    #expect(await api.historyCalls.count == 1)

    await model.consume(jobBatch: batch([.match(stale)]))
    #expect(model.tasks.first?.status == .running)
    #expect(model.tasks.first?.updatedAt == running.updatedAt)
    #expect(await api.matchCalls.isEmpty)

    let terminalOld = changedTask(
      id: active.id, gameID: gameID, status: .succeeded, stage: .ranking, updated: 33)
    let terminalNew = changedTask(
      id: active.id, gameID: gameID, status: .succeeded, stage: .ranking, updated: 35)
    let unknown = changedTask(
      id: unknownResult.id, gameID: id(33), status: .failed, stage: .ranking, updated: 36)
    await model.consume(
      jobBatch: batch([
        .match(terminalOld), .match(terminalNew), .match(terminalOld),
        .match(unknown), .match(unknown),
      ]))

    #expect(await api.matchCalls == [active.id, unknownResult.id])
    #expect(await api.historyCalls.count == 1)
    #expect(model.tasks.first?.id == unknownResult.id)
    #expect(model.tasks.first(where: { $0.id == active.id })?.status == .succeeded)
  }

  @MainActor
  @Test func openResultMapsEmptyPreservesOrderAndFencesLateSelections() async {
    let emptyID = id(40)
    let orderedID = id(41)
    let aID = id(42)
    let bID = id(43)
    let aGate = MatchGate<MatchResult>()
    let ordered = matchResult(
      id: orderedID, gameID: id(4), status: .succeeded, state: .available,
      recommended: [
        candidate(id: id(401), name: "Recommended 1"),
        candidate(id: id(402), name: "Recommended 2"),
      ],
      other: [candidate(id: id(403), name: "Other 1"), candidate(id: id(404), name: "Other 2")])
    let bResult = matchResult(
      id: bID, gameID: id(5), status: .succeeded, state: .available,
      recommended: [candidate(id: id(405), name: "B")], other: [])
    let aResult = matchResult(
      id: aID, gameID: id(6), status: .succeeded, state: .available,
      recommended: [candidate(id: id(406), name: "A")], other: [])
    let api = MatchAPI(
      matchOutcomes: [
        .value(
          matchResult(
            id: emptyID, gameID: id(4), status: .succeeded, state: .noSuitableCreators,
            recommended: [], other: [])),
        .value(ordered),
        .gated(aGate),
        .value(bResult),
      ])
    let model = MatchModel(api: api)

    await model.openResult(id: emptyID)
    #expect(model.resultState == .empty("No suitable creators found"))

    await model.openResult(id: orderedID)
    guard case .available(let result) = model.resultState else {
      Issue.record("Expected an available ordered result")
      return
    }
    #expect(result.recommendedMatches.map(\.id) == [id(401), id(402)])
    #expect(result.otherMatches.map(\.id) == [id(403), id(404)])

    let openA = Task { await model.openResult(id: aID) }
    #expect(await aGate.waitUntilEntered())
    await model.openResult(id: bID)
    aGate.resume(.success(aResult))
    await openA.value
    #expect(model.selectedMatchID == bID)
    #expect(model.resultState == .available(bResult))
  }

  @MainActor
  @Test func terminalRefreshUpdatesSelectedResultWithoutAllowingStaleOpenToWin() async {
    let matchID = id(50)
    let oldResult = matchResult(
      id: matchID, gameID: id(5), status: .running, state: .pending,
      recommended: [], other: [], updated: 50)
    let terminal = matchResult(
      id: matchID, gameID: id(5), status: .succeeded, state: .available,
      recommended: [candidate(id: id(501), name: "Winner")], other: [], updated: 52)
    let api = MatchAPI(matchOutcomes: [.value(oldResult), .value(terminal)])
    let model = MatchModel(api: api)
    await model.openResult(id: matchID)
    #expect(model.resultState == .loading)

    await model.consume(
      jobBatch: batch([
        .match(
          changedTask(
            id: matchID, gameID: id(5), status: .succeeded, stage: .ranking, updated: 52))
      ]))
    #expect(model.resultState == .available(terminal))
    #expect(await api.matchCalls == [matchID, matchID])
  }

  @MainActor
  @Test func retryIsEligibleSingleFlightAmbiguitySafeAndSupportsBothBackendShapes() async {
    let source = matchTask(
      id: id(60), gameID: id(6), status: .failed, retryable: true, created: 60, updated: 60)
    let active = matchTask(
      id: id(61), gameID: id(6), status: .running, created: 61, updated: 61)
    let nonretryable = matchTask(
      id: id(62), gameID: id(6), status: .failed, retryable: false, created: 62, updated: 62)
    let successor = matchTask(
      id: id(63), gameID: id(6), status: .queued, supersedesID: source.id,
      created: 63, updated: 63)
    let sameSource = matchTask(
      id: nonretryable.id, gameID: id(6), status: .running, retryable: false,
      created: 62, updated: 64)
    let gate = MatchGate<MatchTask>()
    let wake = MatchWakeProbe()
    let keys = MatchKeySequence.two
    let api = MatchAPI(
      retryOutcomes: [
        .failure(APIError(code: "lost_retry", message: "Retry response lost.", retryable: true)),
        .gated(gate),
        .value(sameSource),
      ])
    let model = MatchModel(
      api: api, idempotencyKey: keys.provider, onJobActivity: { await wake.record() })

    await model.retry(task: active)
    await model.retry(task: nonretryable)
    #expect(await api.retryCalls.isEmpty)

    await model.retry(task: source)
    #expect(model.actionError == "Retry response lost.")
    let held = Task { await model.retry(task: source) }
    #expect(await gate.waitUntilEntered())
    await model.retry(task: source)
    #expect(await api.retryCalls.count == 2)
    gate.resume(.success(successor))
    await held.value

    #expect(await api.retryCalls.map(\.id) == [source.id, source.id])
    #expect(await api.retryCalls.map(\.key) == [keys.values[0], keys.values[0]])
    #expect(!model.canRetry(task: source))
    #expect(model.tasks.contains(successor))

    let secondSource = matchTask(
      id: nonretryable.id, gameID: id(6), status: .failed, retryable: true,
      created: 62, updated: 62)
    await model.retry(task: secondSource)
    #expect(model.tasks.first(where: { $0.id == secondSource.id })?.status == .running)
    #expect(await api.retryCalls.last == .init(id: secondSource.id, key: keys.values[1]))
    #expect(await wake.count == 2)
  }

  @MainActor
  @Test func matchStagesExposeOnlyExactSemanticCopy() {
    #expect(MatchStage.screening.matchWorkflowLabel == "Screening")
    #expect(MatchStage.pairwise.matchWorkflowLabel == "Comparing Creators")
    #expect(MatchStage.ranking.matchWorkflowLabel == "Ranking")

    let modelProperties = Mirror(reflecting: MatchModel(api: MatchAPI()))
      .children.compactMap(\.label).map { $0.lowercased() }
    #expect(!modelProperties.contains { $0.contains("rank") || $0.contains("score") })
  }
}

private struct ProfileListCall: Sendable, Equatable {
  let type: ProfileType
  let query: String
  let onlyCollection: Bool
  let cursor: String?
  let limit: Int
}

private struct CreateMatchCall: Sendable, Equatable {
  let gameID: UUID
  let key: String
}

private struct RetryMatchCall: Sendable, Equatable {
  let id: UUID
  let key: String
}

private enum MatchOutcome<Value: Sendable>: Sendable {
  case value(Value)
  case failure(APIError)
  case gated(MatchGate<Value>)
}

private final class MatchGate<Value: Sendable>: @unchecked Sendable {
  private let lock = NSLock()
  private var continuation: CheckedContinuation<Result<Value, APIError>, Never>?
  private var entered = false

  func wait() async -> Result<Value, APIError> {
    await withCheckedContinuation { continuation in
      lock.withLock {
        entered = true
        self.continuation = continuation
      }
    }
  }

  func waitUntilEntered() async -> Bool {
    for _ in 0..<1_000 {
      if lock.withLock({ entered }) { return true }
      await Task.yield()
    }
    return lock.withLock { entered }
  }

  func resume(_ result: Result<Value, APIError>) {
    let pending = lock.withLock {
      let pending = continuation
      continuation = nil
      return pending
    }
    pending?.resume(returning: result)
  }
}

private final class MatchKeySequence: @unchecked Sendable {
  static var one: MatchKeySequence {
    MatchKeySequence(["00000000-0000-4000-8000-000000000001"])
  }
  static var two: MatchKeySequence {
    MatchKeySequence([
      "00000000-0000-4000-8000-000000000001",
      "00000000-0000-4000-8000-000000000002",
    ])
  }

  let values: [String]
  private let lock = NSLock()
  private var index = 0

  init(_ values: [String]) { self.values = values }

  var provider: @Sendable () -> String {
    { [self] in
      lock.withLock {
        defer { index += 1 }
        return values[index]
      }
    }
  }
}

private actor MatchWakeProbe {
  private(set) var count = 0
  func record() { count += 1 }
}

private actor MatchAPI: APIService {
  private var profileOutcomes: [MatchOutcome<ProfileCardPage>]
  private var historyOutcomes: [MatchOutcome<MatchTaskPage>]
  private var createOutcomes: [MatchOutcome<MatchTask>]
  private var matchOutcomes: [MatchOutcome<MatchResult>]
  private var retryOutcomes: [MatchOutcome<MatchTask>]

  private(set) var profileCalls: [ProfileListCall] = []
  private(set) var historyCalls: [String?] = []
  private(set) var createCalls: [CreateMatchCall] = []
  private(set) var matchCalls: [UUID] = []
  private(set) var retryCalls: [RetryMatchCall] = []

  init(
    profileOutcomes: [MatchOutcome<ProfileCardPage>] = [],
    historyOutcomes: [MatchOutcome<MatchTaskPage>] = [],
    createOutcomes: [MatchOutcome<MatchTask>] = [],
    matchOutcomes: [MatchOutcome<MatchResult>] = [],
    retryOutcomes: [MatchOutcome<MatchTask>] = []
  ) {
    self.profileOutcomes = profileOutcomes
    self.historyOutcomes = historyOutcomes
    self.createOutcomes = createOutcomes
    self.matchOutcomes = matchOutcomes
    self.retryOutcomes = retryOutcomes
  }

  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    profileCalls.append(
      .init(type: type, query: query, onlyCollection: onlyCollection, cursor: cursor, limit: limit))
    return try await resolve(profileOutcomes.removeFirst())
  }

  func listMatches(cursor: String?) async throws -> MatchTaskPage {
    historyCalls.append(cursor)
    return try await resolve(historyOutcomes.removeFirst())
  }

  func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    createCalls.append(.init(gameID: gameID, key: idempotencyKey))
    return try await resolve(createOutcomes.removeFirst())
  }

  func match(id: UUID) async throws -> MatchResult {
    matchCalls.append(id)
    return try await resolve(matchOutcomes.removeFirst())
  }

  func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    retryCalls.append(.init(id: id, key: idempotencyKey))
    return try await resolve(retryOutcomes.removeFirst())
  }

  private func resolve<Value: Sendable>(_ outcome: MatchOutcome<Value>) async throws -> Value {
    switch outcome {
    case .value(let value): return value
    case .failure(let error): throw error
    case .gated(let gate): return try await gate.wait().get()
    }
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
  fileprivate func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws
    -> ProfileCard
  { fatalError("unused") }
  fileprivate func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  { fatalError("unused") }
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
  { fatalError("unused") }
  fileprivate func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
  fileprivate func smtpSettings() async throws -> SMTPSettingsStatus { fatalError("unused") }
  fileprivate func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    fatalError("unused")
  }
  fileprivate func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws
    -> ConnectionTestResult
  { fatalError("unused") }
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
  fileprivate func testConnection(_ service: ConnectionService) async throws
    -> ConnectionTestResult
  { fatalError("unused") }
}

private func id(_ suffix: Int) -> UUID {
  UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))!
}

private func gameCard(id: UUID, name: String, favorite: Bool) -> GameProfileCard {
  GameProfileCard(
    id: id, name: name, steamAppID: "app-\(id.uuidString.suffix(4))",
    canonicalURL: "https://store.steampowered.com/app/\(id.uuidString.suffix(4))",
    favorite: favorite, currentFacts: [:], brief: [:], sourceStatus: [:],
    lastAnalyzedAt: nil, nextAnalysisAt: nil)
}

private func gameHeader(id: UUID) -> MatchGameHeader {
  MatchGameHeader(
    id: id, name: "Game \(id.uuidString.suffix(4))", steamAppID: "730",
    canonicalURL: "https://store.steampowered.com/app/730", coverURL: nil)
}

private func matchTask(
  id: UUID,
  gameID: UUID,
  status: JobStatus = .queued,
  stage: MatchStage = .screening,
  retryable: Bool = false,
  supersedesID: UUID? = nil,
  created: TimeInterval,
  updated: TimeInterval
) -> MatchTask {
  MatchTask(
    id: id, game: gameHeader(id: gameID), status: status, stage: stage,
    completedUnits: status == .succeeded ? 3 : 0, totalUnits: 3, resultCount: 0,
    retryable: retryable,
    failure: status == .failed ? JobFailure(code: "failed", message: "Safe failure") : nil,
    correlationID: nil, supersedesID: supersedesID,
    createdAt: Date(timeIntervalSince1970: created),
    updatedAt: Date(timeIntervalSince1970: updated), startedAt: nil, completedAt: nil)
}

private func candidate(id: UUID, name: String) -> MatchCandidate {
  MatchCandidate(
    creator: MatchCreatorCard(
      id: id, name: name, youtubeChannelID: "UC\(id.uuidString.suffix(4))",
      canonicalURL: "https://youtube.com/channel/UC\(id.uuidString.suffix(4))",
      favorite: false, contactAvailable: false, contact: nil, avatarURL: nil,
      performanceSummary: nil, subscriberCount: nil, recentAverageViews: nil,
      recentMedianViews: nil),
    group: .recommended, label: .good,
    dimensionOutcomes: MatchDimensionOutcomes(
      contentFit: "Fit", audienceFit: "Fit", performanceFit: "Fit", promotionFit: "Fit",
      brandSafety: "Fit"),
    reasons: ["Reason"],
    brief: MatchBrief(
      contentFit: briefDimension(), audienceFit: briefDimension(),
      performanceFit: briefDimension(), promotionFit: briefDimension(),
      brandSafety: briefDimension(), strengths: [], risks: [], evidence: [], matchReasons: []),
    outreach: MatchOutreach(deliveryID: nil, sendState: nil, responseState: nil))
}

private func briefDimension() -> MatchBriefDimension {
  MatchBriefDimension(analysis: "Analysis", evidence: [])
}

private func matchResult(
  id: UUID,
  gameID: UUID,
  status: JobStatus,
  state: MatchResultState,
  recommended: [MatchCandidate],
  other: [MatchCandidate],
  updated: TimeInterval = 100
) -> MatchResult {
  MatchResult(
    id: id, game: gameHeader(id: gameID), status: status, stage: .ranking,
    completedUnits: status == .succeeded ? 3 : 1, totalUnits: 3,
    resultCount: recommended.count + other.count, retryable: false,
    failure: status == .failed ? JobFailure(code: "failed", message: "Safe failure") : nil,
    correlationID: nil, supersedesID: nil, createdAt: Date(timeIntervalSince1970: 90),
    updatedAt: Date(timeIntervalSince1970: updated), startedAt: nil, completedAt: nil,
    state: state, recommendedMatches: recommended, otherMatches: other)
}

private func changedTask(
  id: UUID, gameID: UUID, status: JobStatus, stage: MatchStage, updated: TimeInterval
) -> ChangedMatchJob {
  ChangedMatchJob(
    id: id, gameID: gameID, status: status, stage: stage,
    completedUnits: status == .succeeded ? 3 : 1, totalUnits: 3, resultCount: 0,
    retryable: status == .failed,
    failure: status == .failed ? JobFailure(code: "failed", message: "Safe failure") : nil,
    correlationID: nil, supersedesID: nil, createdAt: Date(timeIntervalSince1970: 90),
    updatedAt: Date(timeIntervalSince1970: updated), startedAt: nil, completedAt: nil)
}

private func analysisJob(id: UUID) -> AnalysisJob {
  AnalysisJob(
    id: id, profileType: .creator, canonicalTargetID: "UC", canonicalURL: "https://youtube.com/@x",
    mode: .create, status: .succeeded, stage: .finalizing, completedUnits: 3, totalUnits: 3,
    retryable: false, correlationID: nil, profileID: id,
    createdAt: Date(timeIntervalSince1970: 1), updatedAt: Date(timeIntervalSince1970: 2),
    startedAt: nil, completedAt: nil, failure: nil)
}

private func batch(_ changes: [JobChange]) -> JobChangeBatch {
  JobChangeBatch(
    changes: changes, affectedProfileIDs: [], affectedMatchTaskIDs: [], affectedGameIDs: [],
    hasActiveJobs: false)
}
