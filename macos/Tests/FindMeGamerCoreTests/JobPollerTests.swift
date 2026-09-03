import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct JobPollerTests {
  @Test func startIsIdempotentAndImmediatelyUsesOneUnfilteredRequest() async throws {
    let api = JobAPI(steps: [.page(page(cursor: "cursor-1"))])
    let clock = ManualClock()
    let poller = JobPoller(api: api, clock: clock)

    await poller.start()
    await poller.start()
    try await waitUntil { await api.callCount == 1 }

    #expect(await api.calls == [JobListCall(changedAfter: nil, status: nil)])
    #expect(await api.maximumConcurrentCalls == 1)
    #expect(await clock.requestedDurations.isEmpty)
    await poller.stop()
  }

  @Test func activeRegistrySurvivesEmptyPageAndStopsSchedulingAfterTerminalChange() async throws {
    let jobID = UUID(uuidString: "10000000-0000-0000-0000-000000000001")!
    let api = JobAPI(
      steps: [
        .page(page(items: [.analysis(analysis(id: jobID, status: .queued))], cursor: "c1")),
        .page(page(cursor: "c2")),
        .page(page(items: [.analysis(analysis(id: jobID, status: .succeeded))], cursor: "c3")),
      ])
    let clock = ManualClock()
    let poller = JobPoller(api: api, clock: clock)
    let events = EventProbe(stream: poller.events)

    await poller.start()
    try await waitUntil {
      let pendingSleepCount = await clock.pendingSleepCount
      return events.count == 1 && pendingSleepCount == 1
    }
    #expect(events.values[0].hasActiveJobs)
    #expect(await clock.requestedDurations == [.seconds(3)])

    await clock.advance(by: .seconds(3))
    try await waitUntil {
      let callCount = await api.callCount
      let pendingSleepCount = await clock.pendingSleepCount
      return callCount == 2 && pendingSleepCount == 1
    }
    #expect(events.count == 1)
    #expect(await clock.requestedDurations == [.seconds(3), .seconds(3)])

    await clock.advance(by: .seconds(3))
    try await waitUntil { events.count == 2 }
    #expect(!events.values[1].hasActiveJobs)
    #expect(await api.callCount == 3)

    await clock.advance(by: .seconds(30))
    await drainTasks()
    #expect(await api.callCount == 3)
    #expect(await clock.pendingSleepCount == 0)
    await poller.stop()
    events.cancel()
  }

  @Test func multipageSyncIsAtomicOrderedDeduplicatedAndCommitsOpaqueCursor() async throws {
    let analysisID = UUID(uuidString: "20000000-0000-0000-0000-000000000001")!
    let matchID = UUID(uuidString: "20000000-0000-0000-0000-000000000002")!
    let gameID = UUID(uuidString: "20000000-0000-0000-0000-000000000003")!
    let profile1 = UUID(uuidString: "20000000-0000-0000-0000-000000000004")!
    let profile2 = UUID(uuidString: "20000000-0000-0000-0000-000000000005")!
    let profile3 = UUID(uuidString: "20000000-0000-0000-0000-000000000006")!
    let first = JobChange.analysis(analysis(id: analysisID, status: .running))
    let second = JobChange.match(match(id: matchID, gameID: gameID, status: .running))
    let third = JobChange.match(match(id: matchID, gameID: gameID, status: .succeeded))
    let finalCursor = "opaque:\u{2603}/final?x=1&x=2"
    let api = JobAPI(
      steps: [
        .page(
          page(
            items: [first, second], cursor: "opaque:\u{2603}/page-1?x=1&x=2", hasMore: true,
            affectedProfileIDs: [profile1, profile2])),
        .page(
          page(
            items: [third], cursor: finalCursor,
            affectedProfileIDs: [profile2, profile3, profile1])),
        .page(page(cursor: "after-refresh")),
      ])
    let poller = JobPoller(api: api, clock: ManualClock())
    let events = EventProbe(stream: poller.events)

    await poller.start()
    try await waitUntil { events.count == 1 }

    let batch = events.values[0]
    #expect(batch.changes == [first, second, third])
    #expect(batch.affectedProfileIDs == [profile1, profile2, profile3])
    #expect(batch.affectedMatchTaskIDs == [matchID])
    #expect(batch.affectedGameIDs == [gameID])
    #expect(batch.hasActiveJobs)
    #expect(
      await api.calls == [
        JobListCall(changedAfter: nil, status: nil),
        JobListCall(changedAfter: "opaque:\u{2603}/page-1?x=1&x=2", status: nil),
      ])

    await poller.refreshNow()
    try await waitUntil { await api.callCount == 3 }
    #expect(await api.calls[2] == JobListCall(changedAfter: finalCursor, status: nil))
    await poller.stop()
    events.cancel()
  }

  @Test(arguments: [LaterPageFailure.failure, .cancellation])
  func laterPageFailureRollsBackCursorAndEmitsNoPartialBatch(
    failure: LaterPageFailure
  ) async throws {
    let jobID = UUID(uuidString: "30000000-0000-0000-0000-000000000001")!
    let partial = JobChange.analysis(analysis(id: jobID, status: .queued))
    let failedStep: JobAPI.Step = failure == .failure ? .failure : .cancellation
    let api = JobAPI(
      steps: [
        .page(page(cursor: "committed")),
        .page(page(items: [partial], cursor: "uncommitted-page", hasMore: true)),
        failedStep,
        .page(page(items: [partial], cursor: "recovered")),
      ])
    let poller = JobPoller(api: api, clock: ManualClock())
    let events = EventProbe(stream: poller.events)
    await poller.start()
    try await waitUntil { await api.callCount == 1 }

    await poller.refreshNow()
    try await waitUntil { await api.callCount == 3 }
    #expect(events.count == 0)

    await poller.refreshNow()
    try await waitUntil { events.count == 1 }
    #expect(
      await api.calls.map(\.changedAfter) == [nil, "committed", "uncommitted-page", "committed"])
    #expect(events.values[0].changes == [partial])
    await poller.stop()
    events.cancel()
  }

  @Test func refreshCancelsSleepAndCoalescesWhileRequestIsInFlight() async throws {
    let jobID = UUID(uuidString: "40000000-0000-0000-0000-000000000001")!
    let gate = APIGate()
    let queued = JobChange.analysis(analysis(id: jobID, status: .queued))
    let terminal = JobChange.analysis(analysis(id: jobID, status: .succeeded))
    let api = JobAPI(
      steps: [
        .page(page(items: [queued], cursor: "c1")),
        .suspended(gate, page(items: [queued], cursor: "c2")),
        .page(page(items: [terminal], cursor: "c3")),
      ])
    let clock = ManualClock()
    let poller = JobPoller(api: api, clock: clock)
    let events = EventProbe(stream: poller.events)
    await poller.start()
    try await waitUntil { await clock.pendingSleepCount == 1 }

    await poller.refreshNow()
    try await gate.waitUntilEntered()
    #expect(await clock.cancellationCount == 1)

    await poller.refreshNow()
    await poller.refreshNow()
    await poller.refreshNow()
    #expect(await api.callCount == 2)
    #expect(await api.maximumConcurrentCalls == 1)

    gate.resume()
    try await waitUntil {
      let callCount = await api.callCount
      return callCount == 3 && events.count == 3
    }
    #expect(await api.calls.map(\.changedAfter) == [nil, "c1", "c2"])
    #expect(await api.maximumConcurrentCalls == 1)
    #expect(!events.values[2].hasActiveJobs)
    await poller.stop()
    events.cancel()
  }

  @Test func stopCancelsWorkAndRestartUsesTheCommittedCursor() async throws {
    let jobID = UUID(uuidString: "50000000-0000-0000-0000-000000000001")!
    let gate = APIGate()
    let queued = JobChange.match(
      match(
        id: jobID,
        gameID: UUID(uuidString: "50000000-0000-0000-0000-000000000002")!,
        status: .queued))
    let terminal = JobChange.match(
      match(
        id: jobID,
        gameID: UUID(uuidString: "50000000-0000-0000-0000-000000000002")!,
        status: .failed))
    let api = JobAPI(
      steps: [
        .page(page(items: [queued], cursor: "preserved-cursor")),
        .suspended(gate, page(items: [terminal], cursor: "stale-cursor")),
        .page(page(items: [terminal], cursor: "after-restart")),
      ])
    let clock = ManualClock()
    let poller = JobPoller(api: api, clock: clock)
    let events = EventProbe(stream: poller.events)
    await poller.start()
    try await waitUntil { await clock.pendingSleepCount == 1 }

    await poller.stop()
    try await waitUntil { await clock.pendingSleepCount == 0 }
    await clock.advance(by: .seconds(30))
    await drainTasks()
    #expect(await api.callCount == 1)

    await poller.start()
    try await gate.waitUntilEntered()
    await poller.stop()
    gate.resume()
    await drainTasks()
    #expect(events.count == 1)

    await poller.start()
    try await waitUntil {
      let callCount = await api.callCount
      return callCount == 3 && events.count == 2
    }
    #expect(
      await api.calls.map(\.changedAfter) == [nil, "preserved-cursor", "preserved-cursor"])
    #expect(events.values.last?.hasActiveJobs == false)
    await poller.stop()
    events.cancel()
  }

  @Test func streamTerminationCancelsPendingPollingWork() async throws {
    let jobID = UUID(uuidString: "60000000-0000-0000-0000-000000000001")!
    let api = JobAPI(
      steps: [
        .page(
          page(items: [.analysis(analysis(id: jobID, status: .running))], cursor: "cursor"))
      ])
    let clock = ManualClock()
    let poller = JobPoller(api: api, clock: clock)
    let consumer = Task {
      for await _ in poller.events {}
    }
    await poller.start()
    try await waitUntil { await clock.pendingSleepCount == 1 }

    consumer.cancel()
    _ = await consumer.result
    try await waitUntil { await clock.pendingSleepCount == 0 }
    await clock.advance(by: .seconds(30))
    await drainTasks()

    #expect(await api.callCount == 1)
    #expect(await clock.cancellationCount == 1)
  }

  @Test func manualClockRecordsAdvancesAndCancellationWithoutWallTime() async throws {
    let clock = ManualClock()
    let sleeper = Task {
      try await clock.sleep(for: .seconds(3))
    }
    try await waitUntil { await clock.pendingSleepCount == 1 }
    #expect(await clock.requestedDurations == [.seconds(3)])

    sleeper.cancel()
    do {
      try await sleeper.value
      Issue.record("Expected the manual sleep to be cancelled")
    } catch is CancellationError {
      // Expected.
    }

    #expect(await clock.pendingSleepCount == 0)
    #expect(await clock.cancellationCount == 1)
    await clock.advance(by: .seconds(30))
  }
}

enum LaterPageFailure: Sendable {
  case failure
  case cancellation
}

private struct JobListCall: Sendable, Equatable {
  let changedAfter: String?
  let status: JobStatus?
}

private final class EventProbe: @unchecked Sendable {
  private let lock = NSLock()
  private var storage: [JobChangeBatch] = []
  private var task: Task<Void, Never>?

  init(stream: AsyncStream<JobChangeBatch>) {
    task = Task { [weak self] in
      for await value in stream {
        self?.append(value)
      }
    }
  }

  var values: [JobChangeBatch] { lock.withLock { storage } }
  var count: Int { lock.withLock { storage.count } }

  func cancel() {
    task?.cancel()
  }

  private func append(_ value: JobChangeBatch) {
    lock.withLock { storage.append(value) }
  }
}

private final class APIGate: @unchecked Sendable {
  private let lock = NSLock()
  private var continuation: CheckedContinuation<Void, Never>?
  private var entered = false

  func suspend() async {
    await withCheckedContinuation { continuation in
      lock.withLock {
        entered = true
        self.continuation = continuation
      }
    }
  }

  func waitUntilEntered() async throws {
    try await waitUntil { self.lock.withLock { self.entered } }
  }

  func resume() {
    let continuation = lock.withLock {
      let pending = self.continuation
      self.continuation = nil
      return pending
    }
    continuation?.resume()
  }
}

private actor JobAPI: APIService {
  enum Step: Sendable {
    case page(JobChangePage)
    case failure
    case cancellation
    case suspended(APIGate, JobChangePage)
  }

  private var steps: [Step]
  private(set) var calls: [JobListCall] = []
  private var concurrentCalls = 0
  private(set) var maximumConcurrentCalls = 0

  init(steps: [Step]) {
    self.steps = steps
  }

  var callCount: Int { calls.count }

  func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage {
    calls.append(JobListCall(changedAfter: changedAfter, status: status))
    concurrentCalls += 1
    maximumConcurrentCalls = max(maximumConcurrentCalls, concurrentCalls)
    defer { concurrentCalls -= 1 }
    guard !steps.isEmpty else { throw StubError.unexpectedCall }
    let step = steps.removeFirst()
    switch step {
    case .page(let page): return page
    case .failure: throw StubError.transient
    case .cancellation: throw CancellationError()
    case .suspended(let gate, let page):
      await gate.suspend()
      return page
    }
  }

  func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  { fatalError("unused") }
  func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    fatalError("unused")
  }
  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage { fatalError("unused") }
  func profile(type: ProfileType, id: UUID) async throws -> Profile { fatalError("unused") }
  func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws -> ProfileCard {
    fatalError("unused")
  }
  func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  { fatalError("unused") }
  func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  func listMatches(cursor: String?) async throws -> MatchTaskPage { fatalError("unused") }
  func match(id: UUID) async throws -> MatchResult { fatalError("unused") }
  func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  func listCampaigns(cursor: String?) async throws -> CampaignPage { fatalError("unused") }
  func campaign(id: UUID) async throws -> OutreachCampaign { fatalError("unused") }
  func listTemplates() async throws -> [OutreachTemplate] { fatalError("unused") }
  func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  func duplicateTemplate(id: UUID) async throws -> OutreachTemplate { fatalError("unused") }
  func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate { fatalError("unused") }
  func deleteTemplate(id: UUID) async throws { fatalError("unused") }
  func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    fatalError("unused")
  }
  func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    fatalError("unused")
  }
  func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws -> SendBatch
  { fatalError("unused") }
  func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
  func smtpSettings() async throws -> SMTPSettingsStatus { fatalError("unused") }
  func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    fatalError("unused")
  }
  func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws -> ConnectionTestResult {
    fatalError("unused")
  }
  func sendSMTPTest(to email: String) async throws -> ConnectionTestResult { fatalError("unused") }
  func sharedSettings() async throws -> SharedSettings { fatalError("unused") }
  func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    fatalError("unused")
  }
  func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    fatalError("unused")
  }
  func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  { fatalError("unused") }
  func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult {
    fatalError("unused")
  }
}

private enum StubError: Error {
  case transient
  case unexpectedCall
}

private func page(
  items: [JobChange] = [], cursor: String, hasMore: Bool = false,
  affectedProfileIDs: [UUID] = []
) -> JobChangePage {
  JobChangePage(
    items: items, cursor: cursor, hasMore: hasMore, affectedProfileIDs: affectedProfileIDs)
}

private func analysis(id: UUID, status: JobStatus) -> AnalysisJob {
  AnalysisJob(
    id: id, profileType: .creator, canonicalTargetID: "creator", canonicalURL: "https://x.test",
    mode: .create, status: status, stage: status == .succeeded ? nil : .analyzing,
    completedUnits: status == .succeeded ? 1 : 0, totalUnits: 1, retryable: false,
    correlationID: nil, profileID: nil, createdAt: fixtureDate, updatedAt: fixtureDate,
    startedAt: nil, completedAt: status == .succeeded ? fixtureDate : nil, failure: nil)
}

private func match(id: UUID, gameID: UUID, status: JobStatus) -> ChangedMatchJob {
  ChangedMatchJob(
    id: id, gameID: gameID, status: status, stage: .screening,
    completedUnits: status == .succeeded ? 1 : 0, totalUnits: 1, resultCount: 0,
    retryable: false, failure: nil, correlationID: nil, supersedesID: nil,
    createdAt: fixtureDate, updatedAt: fixtureDate, startedAt: nil,
    completedAt: status == .succeeded || status == .failed ? fixtureDate : nil)
}

private let fixtureDate = Date(timeIntervalSince1970: 1_700_000_000)

private func waitUntil(
  attempts: Int = 2_000, _ predicate: @escaping @Sendable () async -> Bool
) async throws {
  for _ in 0..<attempts {
    if await predicate() { return }
    await Task.yield()
  }
  throw StubError.unexpectedCall
}

private func drainTasks() async {
  for _ in 0..<20 {
    await Task.yield()
  }
}
