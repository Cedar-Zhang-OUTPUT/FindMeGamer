import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct AppSessionTests {
  @MainActor
  @Test func missingSavedKeyNeedsInputWithoutCreatingAnAPI() async {
    let store = MemoryWorkspaceKeyStore()
    let api = SessionAPI(outcomes: [.success(testSession)])
    let factory = APIFactoryRecorder(api: api)
    let session = makeSession(store: store, factory: factory)

    await session.restore()

    #expect(session.state == .needsKey)
    #expect(session.service == nil)
    #expect(session.workspaceSession == nil)
    #expect(factory.callCount == 0)
    #expect(await api.validationCount == 0)
  }

  @MainActor
  @Test func validSavedKeyAuthenticatesAndRetainsTheValidatedService() async {
    let store = MemoryWorkspaceKeyStore(value: "saved-key")
    let api = SessionAPI(outcomes: [.success(testSession)])
    let factory = APIFactoryRecorder(api: api)
    let session = makeSession(store: store, factory: factory)

    await session.restore()

    #expect(session.state == .authenticated)
    #expect(session.workspaceSession == testSession)
    #expect(session.service != nil)
    #expect(factory.keys == ["saved-key"])
    #expect(await api.validationCount == 1)
    #expect(await store.deleteCount == 0)
  }

  @MainActor
  @Test func invalidSavedKeyIsTheOnlyAPIErrorThatDeletesIt() async {
    let invalidStore = MemoryWorkspaceKeyStore(value: "SAVED-KEY-CANARY")
    let invalidAPI = SessionAPI(
      outcomes: [
        .api(
          APIError(
            code: "workspace_key_invalid", message: "The workspace key is invalid.",
            retryable: false))
      ])
    let invalidSession = makeSession(
      store: invalidStore, factory: APIFactoryRecorder(api: invalidAPI))

    await invalidSession.restore()

    #expect(invalidSession.state == .needsKey)
    #expect(invalidSession.service == nil)
    #expect(await invalidStore.value == nil)
    #expect(await invalidStore.deleteCount == 1)
    #expect(!invalidSession.message.contains("SAVED-KEY-CANARY"))

    for error in [
      APIError(
        code: "authentication_unavailable", message: "Authentication is temporarily unavailable.",
        retryable: true),
      APIError(code: "rate_limited", message: "Try again later.", retryable: true),
      APIError(code: "server_error", message: "Server unavailable.", retryable: true),
    ] {
      let store = MemoryWorkspaceKeyStore(value: "preserved-key")
      let api = SessionAPI(outcomes: [.api(error)])
      let session = makeSession(store: store, factory: APIFactoryRecorder(api: api))

      await session.restore()

      #expect(session.state == .offline)
      #expect(session.service != nil)
      #expect(await store.value == "preserved-key")
      #expect(await store.deleteCount == 0)
    }
  }

  @MainActor
  @Test func invalidCandidateIsNeverSavedOrDeleted() async {
    let store = MemoryWorkspaceKeyStore(value: "prior-key")
    let api = SessionAPI(
      outcomes: [
        .api(
          APIError(
            code: "workspace_key_invalid", message: "The workspace key is invalid.",
            retryable: false))
      ])
    let session = makeSession(store: store, factory: APIFactoryRecorder(api: api))

    await session.connect(key: "candidate-key")

    #expect(session.state == .needsKey)
    #expect(session.service == nil)
    #expect(await store.value == "prior-key")
    #expect(await store.savedValues.isEmpty)
    #expect(await store.deleteCount == 0)
  }

  @MainActor
  @Test func candidateIsValidatedBeforeItsExactValueIsSaved() async {
    let order = CallOrder()
    let store = MemoryWorkspaceKeyStore(order: order)
    let api = SessionAPI(outcomes: [.success(testSession)], order: order)
    let factory = APIFactoryRecorder(api: api)
    let session = makeSession(store: store, factory: factory)
    let candidate = "  exact workspace key  "

    await session.connect(key: candidate)

    #expect(session.state == .authenticated)
    #expect(order.values == ["validate", "save"])
    #expect(factory.keys == [candidate])
    #expect(await store.savedValues == [candidate])
  }

  @MainActor
  @Test func emptyCandidateFailsLocallyWithoutCreatingAnAPI() async {
    let store = MemoryWorkspaceKeyStore()
    let factory = APIFactoryRecorder(api: SessionAPI(outcomes: [.success(testSession)]))
    let session = makeSession(store: store, factory: factory)

    await session.connect(key: " \n\t ")

    #expect(session.state == .needsKey)
    #expect(factory.callCount == 0)
    #expect(await store.savedValues.isEmpty)
  }

  @MainActor
  @Test func transientCandidateFailureDoesNotPersistOrRetainTheCandidate() async {
    let store = MemoryWorkspaceKeyStore(value: "prior-key")
    let api = SessionAPI(outcomes: [.transport(.timedOut)])
    let factory = APIFactoryRecorder(api: api)
    let session = makeSession(store: store, factory: factory)

    await session.connect(key: "CANDIDATE-KEY-CANARY")

    #expect(session.state == .offline)
    #expect(session.service == nil)
    #expect(session.workspaceSession == nil)
    #expect(await store.value == "prior-key")
    #expect(await store.savedValues.isEmpty)
    #expect(!session.message.contains("CANDIDATE-KEY-CANARY"))
    #expect(!String(describing: session).contains("CANDIDATE-KEY-CANARY"))
  }

  @MainActor
  @Test func retryAfterMissingKeyAndTransientCandidateFailureValidatesTheCandidateAgain() async {
    let store = MemoryWorkspaceKeyStore()
    let api = SessionAPI(outcomes: [.transport(.timedOut), .success(testSession)])
    let factory = APIFactoryRecorder(api: api)
    let session = makeSession(store: store, factory: factory)
    let candidate = "still-local-candidate"

    await session.restore()
    #expect(session.state == .needsKey)

    await session.connect(key: candidate)
    #expect(session.state == .offline)
    #expect(session.service == nil)
    #expect(await store.savedValues.isEmpty)

    await session.retryAccess(key: candidate)

    #expect(session.state == .authenticated)
    #expect(session.workspaceSession == testSession)
    #expect(session.service != nil)
    #expect(factory.keys == [candidate, candidate])
    #expect(await api.validationCount == 2)
    #expect(await store.savedValues == [candidate])
  }

  @MainActor
  @Test func retryWithoutCandidateRerunsRestoreAfterPriorMissingKey() async {
    let store = MemoryWorkspaceKeyStore()
    let api = SessionAPI(outcomes: [.success(testSession)])
    let session = makeSession(store: store, factory: APIFactoryRecorder(api: api))

    await session.restore()
    #expect(session.state == .needsKey)
    #expect(await store.readCount == 1)

    await session.retryAccess(key: " \n\t ")

    #expect(session.state == .needsKey)
    #expect(await store.readCount == 2)
    #expect(await api.validationCount == 0)
  }

  @MainActor
  @Test func transientRestorePreservesKeyAndRecoversOnceWhenConnectivityReturns() async {
    let store = MemoryWorkspaceKeyStore(value: "saved-key")
    let api = SessionAPI(
      outcomes: [.transport(.notConnectedToInternet), .success(testSession)])
    let factory = APIFactoryRecorder(api: api)
    let connectivity = FakeConnectivity()
    let session = makeSession(store: store, factory: factory, connectivity: connectivity)

    await session.restore()

    #expect(session.state == .offline)
    #expect(session.service != nil)
    #expect(await store.value == "saved-key")
    #expect(await store.deleteCount == 0)
    connectivity.emit(false)
    connectivity.emit(true)
    connectivity.emit(true)
    #expect(await eventually { session.state == .authenticated })
    #expect(session.workspaceSession == testSession)
    #expect(await api.validationCount == 2)
    #expect(connectivity.startCount == 1)
  }

  @MainActor
  @Test func repeatedAndConcurrentRestoreCoalescesValidation() async {
    let store = MemoryWorkspaceKeyStore(value: "saved-key")
    let api = SessionAPI(outcomes: [.success(testSession)], validationDelay: .milliseconds(30))
    let session = makeSession(store: store, factory: APIFactoryRecorder(api: api))

    async let first: Void = session.restore()
    async let second: Void = session.restore()
    _ = await (first, second)
    await session.restore()

    #expect(session.state == .authenticated)
    #expect(await api.validationCount == 1)
  }

  @MainActor
  @Test func invalidKeyDuringRecoveryDeletesOnceWithoutAValidationStorm() async {
    let store = MemoryWorkspaceKeyStore(value: "RECOVERY-KEY-CANARY")
    let api = SessionAPI(
      outcomes: [
        .transport(.notConnectedToInternet),
        .api(
          APIError(
            code: "workspace_key_invalid", message: "RECOVERY-KEY-CANARY is invalid.",
            retryable: false)),
      ])
    let connectivity = FakeConnectivity()
    let session = makeSession(
      store: store, factory: APIFactoryRecorder(api: api), connectivity: connectivity)
    await session.restore()

    connectivity.emit(false)
    connectivity.emit(true)
    connectivity.emit(true)

    #expect(await eventually { session.state == .needsKey })
    #expect(session.service == nil)
    #expect(session.workspaceSession == nil)
    #expect(await store.value == nil)
    #expect(await store.deleteCount == 1)
    #expect(await api.validationCount == 2)
    #expect(!session.message.contains("RECOVERY-KEY-CANARY"))
  }

  @MainActor
  @Test func disconnectDeletesOnlyTheLocalItemAndClearsRetainedState() async {
    let store = MemoryWorkspaceKeyStore(value: "saved-key")
    let api = SessionAPI(outcomes: [.success(testSession)])
    let session = makeSession(store: store, factory: APIFactoryRecorder(api: api))
    await session.restore()

    await session.disconnectThisMac()

    #expect(session.state == .needsKey)
    #expect(session.service == nil)
    #expect(session.workspaceSession == nil)
    #expect(await store.deleteCount == 1)
    #expect(await store.value == nil)
    #expect(await api.validationCount == 1)
  }

  @MainActor
  @Test(
    arguments: [SuspendedValidationCompletion.success, .cancelled]
  )
  func disconnectFencesSuspendedRecoveryCompletion(
    completion: SuspendedValidationCompletion
  ) async {
    let gate = ValidationGate()
    let store = MemoryWorkspaceKeyStore(value: "saved-key")
    let api = SessionAPI(
      outcomes: [.success(testSession), .suspended(gate, completion)])
    let connectivity = FakeConnectivity()
    let session = makeSession(
      store: store, factory: APIFactoryRecorder(api: api), connectivity: connectivity)
    await session.restore()

    connectivity.emit(false)
    connectivity.emit(true)
    await gate.waitUntilEntered()

    await session.disconnectThisMac()
    gate.resume()
    await api.waitUntilResolved(count: 2)
    try? await Task.sleep(for: .milliseconds(20))

    #expect(session.state == .needsKey)
    #expect(session.service == nil)
    #expect(session.workspaceSession == nil)
    #expect(await store.value == nil)
    #expect(await store.deleteCount == 1)
    #expect(await api.validationCount == 2)
  }

  @MainActor
  @Test func invalidBundleURLsFailVisiblyWithoutCreatingAnAPI() async {
    for rawValue in [nil, "", "file:///tmp/api", "api/v1", "https:///missing-host"] as [String?] {
      let store = MemoryWorkspaceKeyStore(value: "saved-key")
      let factory = APIFactoryRecorder(api: SessionAPI(outcomes: [.success(testSession)]))
      let session = makeSession(store: store, factory: factory, baseURL: rawValue)

      await session.restore()

      #expect(session.state == .offline)
      #expect(session.service == nil)
      #expect(session.message.contains("configuration"))
      #expect(factory.callCount == 0)
    }
  }

  @MainActor
  @Test func validHTTPAndHTTPSBundleURLsAreAcceptedExactly() async {
    for value in ["http://127.0.0.1:8000", "https://api.example.test/v1"] {
      let store = MemoryWorkspaceKeyStore(value: "saved-key")
      let api = SessionAPI(outcomes: [.success(testSession)])
      let factory = APIFactoryRecorder(api: api)
      let session = makeSession(store: store, factory: factory, baseURL: value)

      await session.restore()

      #expect(session.state == .authenticated)
      #expect(factory.urls.map(\.absoluteString) == [value])
    }
  }

  @MainActor
  @Test func storageFailuresAreSafeAndNeverAuthenticateAfterASaveFailure() async {
    let readStore = MemoryWorkspaceKeyStore(
      readError: CanaryError("KEYCHAIN-READ-SECRET-CANARY"))
    let readSession = makeSession(
      store: readStore,
      factory: APIFactoryRecorder(api: SessionAPI(outcomes: [.success(testSession)])))
    await readSession.restore()
    #expect(readSession.state == .offline)
    #expect(readSession.service == nil)
    #expect(!readSession.message.contains("KEYCHAIN-READ-SECRET-CANARY"))

    let saveStore = MemoryWorkspaceKeyStore(
      value: "prior-key", saveError: CanaryError("CANDIDATE-KEY-CANARY"))
    let saveSession = makeSession(
      store: saveStore,
      factory: APIFactoryRecorder(api: SessionAPI(outcomes: [.success(testSession)])))
    await saveSession.connect(key: "CANDIDATE-KEY-CANARY")
    #expect(saveSession.state == .needsKey)
    #expect(saveSession.service == nil)
    #expect(saveSession.workspaceSession == nil)
    #expect(await saveStore.value == "prior-key")
    #expect(!saveSession.message.contains("CANDIDATE-KEY-CANARY"))

    let deleteStore = MemoryWorkspaceKeyStore(
      value: "saved-key", deleteError: CanaryError("DELETE-SECRET-CANARY"))
    let deleteSession = makeSession(
      store: deleteStore,
      factory: APIFactoryRecorder(api: SessionAPI(outcomes: [.success(testSession)])))
    await deleteSession.restore()
    await deleteSession.disconnectThisMac()
    #expect(deleteSession.state == .offline)
    #expect(deleteSession.service != nil)
    #expect(deleteSession.workspaceSession == testSession)
    #expect(!deleteSession.message.contains("DELETE-SECRET-CANARY"))
  }

  @MainActor
  @Test func cancellationNeverDeletesARestoredKey() async {
    let store = MemoryWorkspaceKeyStore(value: "saved-key")
    let api = SessionAPI(outcomes: [.cancelled])
    let session = makeSession(store: store, factory: APIFactoryRecorder(api: api))

    await session.restore()

    #expect(session.state == .offline)
    #expect(session.service != nil)
    #expect(await store.value == "saved-key")
    #expect(await store.deleteCount == 0)
  }

  @MainActor
  @Test func connectivityLossKeepsAnAuthenticatedWorkspaceAvailableOffline() async {
    let connectivity = FakeConnectivity()
    let session = makeSession(
      store: MemoryWorkspaceKeyStore(value: "saved-key"),
      factory: APIFactoryRecorder(api: SessionAPI(outcomes: [.success(testSession)])),
      connectivity: connectivity)
    await session.restore()

    connectivity.emit(false)

    #expect(await eventually { session.state == .offline })
    #expect(session.service != nil)
    #expect(session.workspaceSession == testSession)
  }
}

private let testSession = WorkspaceSession(
  workspaceName: "Demo", apiVersion: "1.0", serviceConnections: ["steam": true])

@MainActor
private func makeSession(
  store: MemoryWorkspaceKeyStore,
  factory: APIFactoryRecorder,
  connectivity: FakeConnectivity = FakeConnectivity(),
  baseURL: String? = "https://api.example.test"
) -> AppSession {
  AppSession(
    apiFactory: factory.make,
    keyStore: store,
    apiBaseURLProvider: { baseURL },
    connectivity: connectivity)
}

@MainActor
private func eventually(_ predicate: @MainActor () -> Bool) async -> Bool {
  for _ in 0..<100 {
    if predicate() { return true }
    try? await Task.sleep(for: .milliseconds(5))
  }
  return predicate()
}

private struct CanaryError: Error, CustomStringConvertible, Sendable {
  let value: String

  init(_ value: String) {
    self.value = value
  }

  var description: String { value }
}

private final class CallOrder: @unchecked Sendable {
  private let lock = NSLock()
  private var storage: [String] = []

  var values: [String] { lock.withLock { storage } }

  func append(_ value: String) {
    lock.withLock { storage.append(value) }
  }
}

enum SuspendedValidationCompletion: Sendable {
  case success
  case cancelled
}

private final class ValidationGate: @unchecked Sendable {
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

  func waitUntilEntered() async {
    while !lock.withLock({ entered }) {
      await Task.yield()
    }
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

private actor MemoryWorkspaceKeyStore: WorkspaceKeyStore {
  private(set) var value: String?
  private(set) var savedValues: [String] = []
  private(set) var readCount = 0
  private(set) var deleteCount = 0
  private let readError: (any Error)?
  private let saveError: (any Error)?
  private let deleteError: (any Error)?
  private let order: CallOrder?

  init(
    value: String? = nil,
    readError: (any Error)? = nil,
    saveError: (any Error)? = nil,
    deleteError: (any Error)? = nil,
    order: CallOrder? = nil
  ) {
    self.value = value
    self.readError = readError
    self.saveError = saveError
    self.deleteError = deleteError
    self.order = order
  }

  func read() async throws -> String? {
    readCount += 1
    if let readError { throw readError }
    return value
  }

  func save(_ key: String) async throws {
    order?.append("save")
    if let saveError { throw saveError }
    savedValues.append(key)
    value = key
  }

  func delete() async throws {
    deleteCount += 1
    if let deleteError { throw deleteError }
    value = nil
  }
}

private final class APIFactoryRecorder: @unchecked Sendable {
  private let lock = NSLock()
  private let api: SessionAPI
  private var recordedURLs: [URL] = []
  private var recordedKeys: [String] = []

  init(api: SessionAPI) {
    self.api = api
  }

  var callCount: Int { lock.withLock { recordedURLs.count } }
  var urls: [URL] { lock.withLock { recordedURLs } }
  var keys: [String] { lock.withLock { recordedKeys } }

  @MainActor
  func make(baseURL: URL, key: String) -> any APIService {
    lock.withLock {
      recordedURLs.append(baseURL)
      recordedKeys.append(key)
    }
    return api
  }
}

private final class FakeConnectivity: ConnectivityMonitoring, @unchecked Sendable {
  private let lock = NSLock()
  private var handler: (@Sendable (Bool) -> Void)?
  private var starts = 0
  private var cancellations = 0

  var startCount: Int { lock.withLock { starts } }
  var cancelCount: Int { lock.withLock { cancellations } }

  func start(handler: @escaping @Sendable (Bool) -> Void) {
    lock.withLock {
      starts += 1
      if self.handler == nil { self.handler = handler }
    }
  }

  func cancel() {
    lock.withLock {
      cancellations += 1
      handler = nil
    }
  }

  func emit(_ online: Bool) {
    let callback = lock.withLock { handler }
    callback?(online)
  }
}

private actor SessionAPI: APIService {
  enum Outcome: Sendable {
    case success(WorkspaceSession)
    case api(APIError)
    case transport(URLError.Code)
    case cancelled
    case suspended(ValidationGate, SuspendedValidationCompletion)
  }

  private var outcomes: [Outcome]
  private(set) var validationCount = 0
  private var resolvedCount = 0
  private let order: CallOrder?
  private let validationDelay: Duration?

  init(
    outcomes: [Outcome], order: CallOrder? = nil, validationDelay: Duration? = nil
  ) {
    self.outcomes = outcomes
    self.order = order
    self.validationDelay = validationDelay
  }

  func validateSession() async throws -> WorkspaceSession {
    validationCount += 1
    order?.append("validate")
    if let validationDelay { try await Task.sleep(for: validationDelay) }
    let outcome = outcomes.isEmpty ? .success(testSession) : outcomes.removeFirst()
    switch outcome {
    case .success(let session):
      resolvedCount += 1
      return session
    case .api(let error):
      resolvedCount += 1
      throw error
    case .transport(let code):
      resolvedCount += 1
      throw URLError(code)
    case .cancelled:
      resolvedCount += 1
      throw CancellationError()
    case .suspended(let gate, let completion):
      await gate.suspend()
      resolvedCount += 1
      switch completion {
      case .success: return testSession
      case .cancelled: throw CancellationError()
      }
    }
  }

  func waitUntilResolved(count: Int) async {
    while resolvedCount < count {
      await Task.yield()
    }
  }

  func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage {
    fatalError("unused")
  }
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
  {
    fatalError("unused")
  }
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
