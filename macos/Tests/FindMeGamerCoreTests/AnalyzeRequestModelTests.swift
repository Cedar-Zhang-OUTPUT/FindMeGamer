import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct AnalyzeRequestModelTests {
  @MainActor
  @Test func validatesSelectedTargetFamilyBeforeSendingTrimmedSupportedURLs() async {
    let gameJob = analysisJob(
      id: UUID(uuidString: "10000000-0000-4000-8000-000000000001")!, type: .game,
      url: "https://store.steampowered.com/app/730/Counter-Strike-2/?x=1#about")
    let creatorJob = analysisJob(
      id: UUID(uuidString: "10000000-0000-4000-8000-000000000002")!, type: .creator,
      url: "https://www.youtube.com/@Maker")
    let api = AnalyzeAPI(
      submissions: [.value(.job(gameJob)), .value(.job(creatorJob))])
    let model = AnalyzeRequestModel(api: api, idempotencyKey: KeySequence.two.provider)

    let invalid: [(ProfileType, String, String)] = [
      (.game, "https://youtube.com/@maker", "Enter a Steam game page URL."),
      (.creator, "https://store.steampowered.com/app/730", "Enter a YouTube creator page URL."),
      (.game, "http://store.steampowered.com/app/730", "Enter a Steam game page URL."),
      (.game, "https://store.steampowered.com.evil.test/app/730", "Enter a Steam game page URL."),
      (.game, "https://user@store.steampowered.com/app/730", "Enter a Steam game page URL."),
      (.creator, "https://youtube.com:443/@maker", "Enter a YouTube creator page URL."),
      (.creator, "/@maker", "Enter a YouTube creator page URL."),
    ]
    for (type, url, message) in invalid {
      model.targetType = type
      model.urlText = url
      await model.submit()
      #expect(model.validationMessage == message)
    }
    #expect(await api.createCalls.isEmpty)

    model.targetType = .game
    model.urlText = "  https://store.steampowered.com/app/730/Counter-Strike-2/?x=1#about\n"
    await model.submit()
    model.targetType = .creator
    model.urlText = "\nhttps://www.youtube.com/@Maker  "
    await model.submit()

    #expect(
      await api.createCalls.map(\.request) == [
        AnalysisRequest(
          url: "https://store.steampowered.com/app/730/Counter-Strike-2/?x=1#about",
          profileType: .game, mode: .create),
        AnalysisRequest(
          url: "https://www.youtube.com/@Maker", profileType: .creator, mode: .create),
      ])
    #expect(await api.createCalls.map(\.key) == KeySequence.two.values)
    #expect(model.validationMessage == nil)
  }

  @MainActor
  @Test func heldSubmitSurvivesInspectorCloseAndMergesPollingUpdateOnce() async {
    let gate = AnalyzeGate<AnalysisSubmission>()
    let wake = WakeProbe()
    let id = UUID(uuidString: "20000000-0000-4000-8000-000000000001")!
    let queued = analysisJob(id: id, status: .queued)
    let running = analysisJob(id: id, status: .running, stage: .analyzing)
    let api = AnalyzeAPI(submissions: [.gated(gate)])
    let model = AnalyzeRequestModel(
      api: api, idempotencyKey: KeySequence.one.provider,
      onJobActivity: { await wake.record() })
    model.urlText = "https://youtube.com/channel/UC123"
    model.inspectorPresented = true

    let submission = Task { await model.submit() }
    #expect(await gate.waitUntilEntered())
    #expect(model.isSubmitting)
    await model.submit()
    #expect(await api.createCalls.count == 1)
    model.inspectorPresented = false
    gate.resume(.success(.job(queued)))
    await submission.value

    #expect(model.jobs == [queued])
    #expect(await wake.count == 1)
    model.consume(
      jobBatch: JobChangeBatch(
        changes: [.analysis(running)], affectedProfileIDs: [], affectedMatchTaskIDs: [],
        affectedGameIDs: [], hasActiveJobs: true))
    #expect(model.jobs == [running])
    #expect(model.activeJobCount == 1)
    #expect(!model.inspectorPresented)
  }

  @MainActor
  @Test func existingProfileAddsNoJobAndReanalysisUsesItsExactCanonicalIdentity() async {
    let wake = WakeProbe()
    let profile = ExistingProfile(
      profileID: UUID(uuidString: "30000000-0000-4000-8000-000000000001")!,
      profileType: .creator, canonicalTargetID: "UC-existing",
      canonicalURL: "https://youtube.com/channel/UC-existing")
    let reanalysis = analysisJob(
      id: UUID(uuidString: "30000000-0000-4000-8000-000000000002")!, type: .creator,
      url: profile.canonicalURL, mode: .reanalyze)
    let keys = KeySequence.two
    let api = AnalyzeAPI(
      submissions: [.value(.existingProfile(profile)), .value(.job(reanalysis))])
    let model = AnalyzeRequestModel(
      api: api, idempotencyKey: keys.provider, onJobActivity: { await wake.record() })
    model.urlText = "https://youtube.com/@existing"

    await model.submit()
    #expect(model.existingProfile == profile)
    #expect(model.jobs.isEmpty)
    #expect(await wake.count == 0)

    await model.reanalyze(.profile(profile))
    #expect(
      await api.createCalls.map(\.request) == [
        AnalysisRequest(
          url: "https://youtube.com/@existing", profileType: .creator, mode: .create),
        AnalysisRequest(url: profile.canonicalURL, profileType: .creator, mode: .reanalyze),
      ])
    #expect(await api.createCalls.map(\.key) == keys.values)
    #expect(model.existingProfile == nil)
    #expect(model.jobs == [reanalysis])
    #expect(await wake.count == 1)
  }

  @MainActor
  @Test func batchesIgnoreMatchUpsertByIDSortDeterministicallyAndDriveActiveCount() {
    let api = AnalyzeAPI()
    let model = AnalyzeRequestModel(api: api)
    let olderID = UUID(uuidString: "40000000-0000-4000-8000-000000000003")!
    let tieA = UUID(uuidString: "40000000-0000-4000-8000-000000000001")!
    let tieB = UUID(uuidString: "40000000-0000-4000-8000-000000000002")!
    let older = analysisJob(
      id: olderID, status: .queued, createdAt: Date(timeIntervalSince1970: 10))
    let tieAQueued = analysisJob(
      id: tieA, status: .queued, createdAt: Date(timeIntervalSince1970: 20))
    let tieATerminal = analysisJob(
      id: tieA, status: .succeeded, createdAt: Date(timeIntervalSince1970: 20),
      updatedAt: Date(timeIntervalSince1970: 21))
    let tieBRunning = analysisJob(
      id: tieB, status: .running, stage: .fetchingData,
      createdAt: Date(timeIntervalSince1970: 20))

    model.consume(
      jobBatch: JobChangeBatch(
        changes: [
          .analysis(older), .analysis(tieBRunning), .match(changedMatch()),
          .analysis(tieATerminal), .analysis(tieAQueued),
        ], affectedProfileIDs: [], affectedMatchTaskIDs: [], affectedGameIDs: [],
        hasActiveJobs: true))

    #expect(model.jobs.map(\.id) == [tieA, tieB, olderID])
    #expect(model.jobs[0].status == .succeeded)
    #expect(model.activeJobCount == 2)

    let tieBTerminal = analysisJob(
      id: tieB, status: .failed, createdAt: Date(timeIntervalSince1970: 20))
    model.consume(
      jobBatch: JobChangeBatch(
        changes: [
          .analysis(tieBTerminal),
          .analysis(
            analysisJob(
              id: olderID, status: .superseded, createdAt: Date(timeIntervalSince1970: 10))),
        ],
        affectedProfileIDs: [], affectedMatchTaskIDs: [], affectedGameIDs: [],
        hasActiveJobs: false))
    #expect(model.jobs.count == 3)
    #expect(model.activeJobCount == 0)
  }

  @MainActor
  @Test func retryAcceptsOnlyRetryableFailureIsSingleFlightAndAllowsLaterExplicitAttempt() async {
    let gate = AnalyzeGate<AnalysisJob>()
    let wake = WakeProbe()
    let failed = analysisJob(
      id: UUID(uuidString: "50000000-0000-4000-8000-000000000001")!, status: .failed,
      retryable: true)
    let running = analysisJob(
      id: UUID(uuidString: "50000000-0000-4000-8000-000000000002")!, status: .running)
    let nonretryable = analysisJob(
      id: UUID(uuidString: "50000000-0000-4000-8000-000000000003")!, status: .failed)
    let replacement = analysisJob(
      id: UUID(uuidString: "50000000-0000-4000-8000-000000000004")!, status: .queued)
    let keys = KeySequence.two
    let api = AnalyzeAPI(
      retries: [
        .gated(gate),
        .failure(APIError(code: "retry_failed", message: "Retry unavailable.", retryable: true)),
      ])
    let model = AnalyzeRequestModel(
      api: api, idempotencyKey: keys.provider, onJobActivity: { await wake.record() })
    model.consume(
      jobBatch: JobChangeBatch(
        changes: [.analysis(failed)], affectedProfileIDs: [], affectedMatchTaskIDs: [],
        affectedGameIDs: [], hasActiveJobs: false))

    await model.retry(job: running)
    await model.retry(job: nonretryable)
    #expect(await api.retryCalls.isEmpty)

    let attempt = Task { await model.retry(job: failed) }
    #expect(await gate.waitUntilEntered())
    await model.retry(job: failed)
    #expect(await api.retryCalls.count == 1)
    gate.resume(.success(replacement))
    await attempt.value
    #expect(model.jobs.contains(replacement))
    #expect(await wake.count == 1)

    await model.retry(job: failed)
    #expect(await api.retryCalls.map(\.id) == [failed.id, failed.id])
    #expect(await api.retryCalls.map(\.key) == keys.values)
    #expect(model.actionError == "Retry unavailable.")
    #expect(model.jobs.contains(replacement))
    #expect(model.retryingJobIDs.isEmpty)
    #expect(await wake.count == 1)
  }

  @MainActor
  @Test func jobReanalysisRejectsUnsupportedInputAndSuppressesDuplicateMutation() async {
    let gate = AnalyzeGate<AnalysisSubmission>()
    let wake = WakeProbe()
    let existing = ExistingProfile(
      profileID: UUID(uuidString: "60000000-0000-4000-8000-000000000001")!,
      profileType: .game, canonicalTargetID: "730",
      canonicalURL: "https://store.steampowered.com/app/730")
    let active = analysisJob(
      id: UUID(uuidString: "60000000-0000-4000-8000-000000000002")!, type: .game,
      status: .running)
    let successful = analysisJob(
      id: UUID(uuidString: "60000000-0000-4000-8000-000000000003")!, type: .game,
      url: "https://store.steampowered.com/app/440", status: .succeeded,
      profileID: UUID(uuidString: "60000000-0000-4000-8000-000000000004")!)
    let returned = analysisJob(
      id: UUID(uuidString: "60000000-0000-4000-8000-000000000005")!, type: .game,
      url: successful.canonicalURL, mode: .reanalyze)
    let keys = KeySequence.two
    let api = AnalyzeAPI(
      submissions: [.value(.existingProfile(existing)), .gated(gate)])
    let model = AnalyzeRequestModel(
      api: api, idempotencyKey: keys.provider, onJobActivity: { await wake.record() })
    model.targetType = .game
    model.urlText = existing.canonicalURL
    await model.submit()

    await model.reanalyze(.job(active))
    #expect(await api.createCalls.count == 1)

    let request = Task { await model.reanalyze(.job(successful)) }
    #expect(await gate.waitUntilEntered())
    await model.reanalyze(.job(successful))
    #expect(await api.createCalls.count == 2)
    #expect(model.reanalyzingJobIDs == [successful.id])
    gate.resume(.success(.job(returned)))
    await request.value

    #expect(
      await api.createCalls[1].request
        == AnalysisRequest(url: successful.canonicalURL, profileType: .game, mode: .reanalyze))
    #expect(model.reanalyzingJobIDs.isEmpty)
    #expect(model.existingProfile == nil)
    #expect(model.jobs == [returned])
    #expect(await wake.count == 1)
  }

  @MainActor
  @Test func retryFailureReplacesStaleSubmitValidationWithItsOwnFeedback() async {
    let failed = analysisJob(status: .failed, retryable: true)
    let api = AnalyzeAPI(
      retries: [
        .failure(
          APIError(
            code: "retry_failed", message: "Retry is temporarily unavailable.", retryable: true)
        )
      ])
    let model = AnalyzeRequestModel(api: api, idempotencyKey: KeySequence.one.provider)

    model.urlText = "not a supported URL"
    await model.submit()
    #expect(model.validationMessage == "Enter a YouTube creator page URL.")

    await model.retry(job: failed)

    #expect(model.validationMessage == nil)
    #expect(model.actionError == "Retry is temporarily unavailable.")
    #expect(await api.retryCalls.map(\.id) == [failed.id])
  }

  @MainActor
  @Test func reanalysisFailureAndSuccessReplaceStaleSubmitValidation() async {
    let profile = ExistingProfile(
      profileID: UUID(uuidString: "61000000-0000-4000-8000-000000000001")!,
      profileType: .creator, canonicalTargetID: "UC-existing",
      canonicalURL: "https://youtube.com/channel/UC-existing")
    let returned = analysisJob(
      id: UUID(uuidString: "61000000-0000-4000-8000-000000000002")!,
      url: profile.canonicalURL, mode: .reanalyze)
    let api = AnalyzeAPI(
      submissions: [
        .failure(
          APIError(
            code: "reanalyze_failed", message: "Re-analysis is temporarily unavailable.",
            retryable: true)),
        .value(.job(returned)),
      ])
    let model = AnalyzeRequestModel(api: api, idempotencyKey: KeySequence.two.provider)

    model.urlText = "invalid"
    await model.submit()
    #expect(model.validationMessage == "Enter a YouTube creator page URL.")

    await model.reanalyze(.profile(profile))
    #expect(model.validationMessage == nil)
    #expect(model.actionError == "Re-analysis is temporarily unavailable.")

    await model.submit()
    #expect(model.validationMessage == "Enter a YouTube creator page URL.")
    await model.reanalyze(.profile(profile))

    #expect(model.validationMessage == nil)
    #expect(model.actionError == nil)
    #expect(model.jobs == [returned])
    #expect(model.existingProfile == nil)
  }
}

private struct CreateCall: Sendable, Equatable {
  let request: AnalysisRequest
  let key: String
}

private struct RetryCall: Sendable, Equatable {
  let id: UUID
  let key: String
}

private enum AnalyzeOutcome<Value: Sendable>: Sendable {
  case value(Value)
  case failure(APIError)
  case gated(AnalyzeGate<Value>)
}

private final class AnalyzeGate<Value: Sendable>: @unchecked Sendable {
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

private final class KeySequence: @unchecked Sendable {
  static var one: KeySequence {
    KeySequence(["00000000-0000-4000-8000-000000000001"])
  }
  static var two: KeySequence {
    KeySequence([
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

private actor WakeProbe {
  private(set) var count = 0
  func record() { count += 1 }
}

private actor AnalyzeAPI: APIService {
  private var submissions: [AnalyzeOutcome<AnalysisSubmission>]
  private var retries: [AnalyzeOutcome<AnalysisJob>]
  private(set) var createCalls: [CreateCall] = []
  private(set) var retryCalls: [RetryCall] = []

  init(
    submissions: [AnalyzeOutcome<AnalysisSubmission>] = [],
    retries: [AnalyzeOutcome<AnalysisJob>] = []
  ) {
    self.submissions = submissions
    self.retries = retries
  }

  func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  {
    createCalls.append(CreateCall(request: request, key: idempotencyKey))
    return try await resolve(submissions.removeFirst())
  }

  func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    retryCalls.append(RetryCall(id: id, key: idempotencyKey))
    return try await resolve(retries.removeFirst())
  }

  private func resolve<Value: Sendable>(_ outcome: AnalyzeOutcome<Value>) async throws -> Value {
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
  fileprivate func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage { fatalError("unused") }
  fileprivate func profile(type: ProfileType, id: UUID) async throws -> Profile {
    fatalError("unused")
  }
  fileprivate func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws
    -> ProfileCard
  { fatalError("unused") }
  fileprivate func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  { fatalError("unused") }
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

private func analysisJob(
  id: UUID = UUID(), type: ProfileType = .creator,
  url: String = "https://youtube.com/channel/UC123", mode: AnalysisMode = .create,
  status: JobStatus = .queued, stage: AnalysisStage? = nil, retryable: Bool = false,
  profileID: UUID? = nil, createdAt: Date = Date(timeIntervalSince1970: 100),
  updatedAt: Date? = nil
) -> AnalysisJob {
  AnalysisJob(
    id: id, profileType: type, canonicalTargetID: "target", canonicalURL: url, mode: mode,
    status: status, stage: stage, completedUnits: 0, totalUnits: 1, retryable: retryable,
    correlationID: nil, profileID: profileID, createdAt: createdAt,
    updatedAt: updatedAt ?? createdAt,
    startedAt: nil, completedAt: nil,
    failure: status == .failed ? JobFailure(code: "failed", message: "Safe failure") : nil)
}

private func changedMatch() -> ChangedMatchJob {
  ChangedMatchJob(
    id: UUID(), gameID: UUID(), status: .running, stage: .screening, completedUnits: 0,
    totalUnits: 1, resultCount: 0, retryable: false, failure: nil, correlationID: nil,
    supersedesID: nil, createdAt: .distantPast, updatedAt: .distantPast, startedAt: nil,
    completedAt: nil)
}
