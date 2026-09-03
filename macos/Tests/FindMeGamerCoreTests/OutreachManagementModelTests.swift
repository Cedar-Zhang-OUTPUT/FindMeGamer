import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct OutreachManagementModelTests {
  @MainActor
  @Test func campaignsAreDefaultAndTemplateDefaultsAreExact() {
    let model = OutreachManagementModel(api: ManagementAPI())

    #expect(model.selectedTab == .campaigns)
    #expect(
      OutreachManagementModel.allowedVariables == [
        "{{creator_name}}", "{{channel_name}}", "{{game_name}}", "{{steam_url}}",
        "{{game_summary}}", "{{match_reason}}", "{{sender_name}}",
      ])

    model.beginCreatingTemplate()
    #expect(model.templateDraft?.id == nil)
    #expect(model.templateDraft?.acceptedLabel == "Yes, I'm in")
    #expect(model.templateDraft?.declinedLabel == "No, I'm not interested")
    #expect(model.previewState == .saveFirst("Save the Template to preview it."))
    #expect(!model.canSaveTemplate)
  }

  @MainActor
  @Test func campaignPagingIsAtomicOrderedAndDeduplicated() async {
    let first = campaignSummary(id: id(1), game: "First")
    let second = campaignSummary(id: id(2), game: "Second")
    let api = ManagementAPI(
      campaignPageOutcomes: [
        .value(CampaignPage(items: [first], cursor: "opaque +/ cursor", hasMore: true)),
        .value(CampaignPage(items: [first, second], cursor: nil, hasMore: false)),
        .value(CampaignPage(items: [second], cursor: "failure cursor", hasMore: true)),
        .failure(APIError(code: "page_failed", message: "Safe page failure", retryable: true)),
      ])
    let model = OutreachManagementModel(api: api)

    await model.loadCampaigns()
    #expect(model.campaigns == [first, second])
    #expect(await api.campaignPageCalls == [nil, "opaque +/ cursor"])

    let committed = model.campaigns
    await model.loadCampaigns()
    #expect(model.campaigns == committed)
    #expect(model.campaignsError == "Safe page failure")
    #expect(await api.campaignPageCalls.suffix(2) == [nil, "failure cursor"])
  }

  @MainActor
  @Test func newerCampaignSelectionFencesHeldOldSuccessAndFailure() async {
    let aID = id(10)
    let bID = id(11)
    let aGate = ManagementGate<OutreachCampaign>()
    let api = ManagementAPI(
      campaignOutcomes: [
        .gated(aGate),
        .value(campaign(id: bID, game: "B", deliveries: [delivery(id: id(111))])),
      ])
    let model = OutreachManagementModel(api: api)

    let openA = Task { await model.openCampaign(id: aID) }
    #expect(await aGate.waitUntilEntered())
    await model.openCampaign(id: bID)
    #expect(model.selectedCampaignID == bID)
    #expect(model.selectedCampaign?.id == bID)

    aGate.resume(.failure(APIError(code: "late_a", message: "Late A", retryable: true)))
    await openA.value
    #expect(model.selectedCampaignID == bID)
    #expect(model.selectedCampaign?.id == bID)
    #expect(model.campaignError == nil)
    #expect(await api.campaignCalls == [aID, bID])
  }

  @MainActor
  @Test func templateLoadChoosesDefaultAndEditingDoesNotMutateCanonicalTemplates() async {
    let first = template(id: id(20), name: "First", isDefault: false)
    let preferred = template(id: id(21), name: "Preferred", isDefault: true)
    let api = ManagementAPI(
      templateListOutcomes: [
        .value([first, preferred]),
        .failure(
          APIError(
            code: "templates_failed", message: "Safe template failure", retryable: true)),
      ])
    let model = OutreachManagementModel(api: api, clock: ManualClock())

    await model.loadTemplates()
    #expect(model.templates == [first, preferred])
    #expect(model.selectedTemplateID == preferred.id)
    #expect(model.templateDraft?.name == "Preferred")

    model.editTemplateName("Unsaved local name")
    model.editTemplateBody("Unsaved **Markdown**")
    #expect(model.templates == [first, preferred])
    #expect(model.templateDraft?.name == "Unsaved local name")
    #expect(model.templateDraft?.bodyMarkdown == "Unsaved **Markdown**")

    let committed = model.templates
    await model.loadTemplates()
    #expect(model.templates == committed)
    #expect(model.templatesError == "Safe template failure")
  }

  @MainActor
  @Test func savedPreviewDebouncesExactDraftAndFencesStaleFailure() async {
    let clock = ManualClock()
    let oldGate = ManagementGate<RenderedEmail>()
    let saved = template(id: id(30), name: "Saved", isDefault: true)
    let newestPreview = RenderedEmail(
      subject: "Newest Subject", markdown: "Newest", html: "<p>Newest</p>")
    let api = ManagementAPI(
      templateListOutcomes: [.value([saved])],
      previewOutcomes: [.gated(oldGate), .value(newestPreview)])
    let model = OutreachManagementModel(api: api, clock: clock)
    await model.loadTemplates()
    #expect(await waitUntil { await clock.pendingSleepCount == 1 })

    model.editTemplateBody("First edit")
    model.editTemplateBody("Final edit")
    #expect(await waitUntil { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(299))
    #expect(await api.previewCalls.isEmpty)
    await clock.advance(by: .milliseconds(1))
    #expect(await oldGate.waitUntilEntered())
    #expect(await api.previewCalls.map(\.bodyMarkdown) == ["Final edit"])

    model.editTemplateSubject("Newest subject template")
    #expect(await waitUntil { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(300))
    #expect(await waitUntil { await api.previewCalls.count == 2 })
    #expect(await api.previewCalls.last?.subjectTemplate == "Newest subject template")
    #expect(await waitUntil { await model.previewState == .available(newestPreview) })

    oldGate.resume(.failure(APIError(code: "stale", message: "Stale failure", retryable: true)))
    #expect(await waitUntil { await api.previewCalls.count == 2 })
    #expect(model.previewState == .available(newestPreview))
    #expect(await clock.requestedDurations.allSatisfy { $0 == .milliseconds(300) })

    model.beginCreatingTemplate()
    model.editTemplateBody("New unsaved body")
    await clock.advance(by: .milliseconds(300))
    #expect(await api.previewCalls.count == 2)
    #expect(model.previewState == .saveFirst("Save the Template to preview it."))
  }

  @MainActor
  @Test func saveIsSingleFlightAndUpsertsCanonicalResponse() async {
    let source = template(id: id(40), name: "Source", isDefault: true)
    let canonical = template(
      id: source.id, name: "Canonical", subject: "Canonical subject", body: "Canonical body",
      isDefault: true, version: 2)
    let gate = ManagementGate<OutreachTemplate>()
    let api = ManagementAPI(
      templateListOutcomes: [.value([source])], saveOutcomes: [.gated(gate)])
    let model = OutreachManagementModel(api: api, clock: ManualClock())
    await model.loadTemplates()
    model.editTemplateName("Submitted name")
    model.editTemplateSubject("Submitted subject")
    model.editTemplateBody("Submitted body")
    let submitted = model.templateDraft

    let save = Task { await model.saveTemplate() }
    #expect(await gate.waitUntilEntered())
    #expect(model.isTemplateActionInFlight)
    #expect(!model.canSaveTemplate)
    await model.saveTemplate()
    #expect(await api.saveCalls == [submitted])
    gate.resume(.success(canonical))
    await save.value

    #expect(model.templates == [canonical])
    #expect(model.selectedTemplateID == canonical.id)
    #expect(model.templateDraft == TemplateDraft(template: canonical))
    #expect(!model.isTemplateActionInFlight)
  }

  @MainActor
  @Test func duplicateDefaultAndDeleteUseExactSelectionAndRetainOnFailure() async {
    let first = template(id: id(50), name: "First", isDefault: true)
    let second = template(id: id(51), name: "Second", isDefault: false)
    let duplicate = template(id: id(52), name: "Second copy", isDefault: false)
    let madeDefault = template(id: duplicate.id, name: duplicate.name, isDefault: true)
    let api = ManagementAPI(
      templateListOutcomes: [.value([first, second])],
      duplicateOutcomes: [.value(duplicate)], defaultOutcomes: [.value(madeDefault)],
      deleteOutcomes: [
        .success(()),
        .failure(
          APIError(
            code: "cannot_delete", message: "Keep the last Template.", retryable: false)),
      ])
    let model = OutreachManagementModel(api: api, clock: ManualClock())
    await model.loadTemplates()
    model.selectTemplate(id: second.id)

    await model.duplicateSelectedTemplate()
    #expect(await api.duplicateCalls == [second.id])
    #expect(model.templates.map(\.id) == [first.id, second.id, duplicate.id])
    #expect(model.selectedTemplateID == duplicate.id)

    await model.setSelectedTemplateDefault()
    #expect(await api.defaultCalls == [duplicate.id])
    #expect(model.templates.filter(\.isDefault).map(\.id) == [duplicate.id])

    await model.deleteSelectedTemplate()
    #expect(await api.deleteCalls == [duplicate.id])
    #expect(model.templates.map(\.id) == [first.id, second.id])
    #expect(model.selectedTemplateID == first.id)

    model.selectTemplate(id: second.id)
    let retained = model.templates
    await model.deleteSelectedTemplate()
    #expect(await api.deleteCalls == [duplicate.id, second.id])
    #expect(model.templates == retained)
    #expect(model.selectedTemplateID == second.id)
    #expect(model.templateActionError == "Keep the last Template.")
  }

  @MainActor
  @Test func resendReusesAmbiguousKeySuppressesDoubleClickAndOwnsRefreshFailure() async {
    let campaignID = id(60)
    let sourceID = id(61)
    let accepted = delivery(id: id(62), resends: sourceID)
    let gate = ManagementGate<Delivery>()
    let keys = ManagementKeySequence.one
    let api = ManagementAPI(
      campaignOutcomes: [
        .value(campaign(id: campaignID, game: "Selected", deliveries: [delivery(id: sourceID)])),
        .failure(APIError(code: "refresh_failed", message: "Refresh failed.", retryable: true)),
      ],
      resendOutcomes: [
        .failure(APIError(code: "response_lost", message: "Response lost.", retryable: true)),
        .gated(gate),
      ])
    let model = OutreachManagementModel(api: api, idempotencyKey: keys.provider)
    await model.openCampaign(id: campaignID)

    await model.resendDelivery(id: sourceID)
    #expect(model.resendError == "Response lost.")
    let retry = Task { await model.resendDelivery(id: sourceID) }
    #expect(await gate.waitUntilEntered())
    await model.resendDelivery(id: sourceID)
    #expect(await api.resendCalls.count == 2)
    gate.resume(.success(accepted))
    await retry.value

    #expect(await api.resendCalls.map(\.id) == [sourceID, sourceID])
    #expect(await api.resendCalls.map(\.key) == [keys.values[0], keys.values[0]])
    #expect(model.lastResentDelivery == accepted)
    #expect(model.resendError == nil)
    #expect(model.resendMessage == "Resend accepted.")
    #expect(!model.canAttemptResend(id: sourceID))
    #expect(model.selectedCampaign?.id == campaignID)
    #expect(model.campaignError == "Refresh failed.")
    #expect(await api.campaignCalls == [campaignID, campaignID])

    await model.resendDelivery(id: sourceID)
    #expect(await api.resendCalls.count == 2)
  }

  @MainActor
  @Test func resendRejectsMismatchedIdentityAndReusesItsKey() async {
    let sourceID = id(70)
    let keys = ManagementKeySequence.one
    let mismatched = delivery(id: id(71), resends: id(999))
    let accepted = delivery(id: id(72), resends: sourceID)
    let api = ManagementAPI(resendOutcomes: [.value(mismatched), .value(accepted)])
    let model = OutreachManagementModel(api: api, idempotencyKey: keys.provider)

    await model.resendDelivery(id: sourceID)
    #expect(model.lastResentDelivery == nil)
    #expect(model.resendError == "Could not verify the resent Delivery.")
    #expect(model.canAttemptResend(id: sourceID))

    await model.resendDelivery(id: sourceID)
    #expect(await api.resendCalls.map(\.key) == [keys.values[0], keys.values[0]])
    #expect(model.lastResentDelivery == accepted)
    #expect(!model.canAttemptResend(id: sourceID))
  }
}

private struct CampaignPageCall: Sendable, Equatable {
  let cursor: String?
}

private struct ResendCall: Sendable, Equatable {
  let id: UUID
  let key: String
}

private enum ManagementOutcome<Value: Sendable>: Sendable {
  case value(Value)
  case failure(APIError)
  case gated(ManagementGate<Value>)
}

private enum VoidOutcome: Sendable {
  case success(Void)
  case failure(APIError)
}

private final class ManagementGate<Value: Sendable>: @unchecked Sendable {
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

private final class ManagementKeySequence: @unchecked Sendable {
  static var one: ManagementKeySequence {
    ManagementKeySequence(["00000000-0000-4000-8000-000000000001"])
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

private actor ManagementAPI: APIService {
  private var campaignPageOutcomes: [ManagementOutcome<CampaignPage>]
  private var campaignOutcomes: [ManagementOutcome<OutreachCampaign>]
  private var templateListOutcomes: [ManagementOutcome<[OutreachTemplate]>]
  private var saveOutcomes: [ManagementOutcome<OutreachTemplate>]
  private var duplicateOutcomes: [ManagementOutcome<OutreachTemplate>]
  private var defaultOutcomes: [ManagementOutcome<OutreachTemplate>]
  private var deleteOutcomes: [VoidOutcome]
  private var previewOutcomes: [ManagementOutcome<RenderedEmail>]
  private var resendOutcomes: [ManagementOutcome<Delivery>]

  private(set) var campaignPageCalls: [String?] = []
  private(set) var campaignCalls: [UUID] = []
  private(set) var saveCalls: [TemplateDraft] = []
  private(set) var duplicateCalls: [UUID] = []
  private(set) var defaultCalls: [UUID] = []
  private(set) var deleteCalls: [UUID] = []
  private(set) var previewCalls: [TemplateDraft] = []
  private(set) var resendCalls: [ResendCall] = []

  init(
    campaignPageOutcomes: [ManagementOutcome<CampaignPage>] = [],
    campaignOutcomes: [ManagementOutcome<OutreachCampaign>] = [],
    templateListOutcomes: [ManagementOutcome<[OutreachTemplate]>] = [],
    saveOutcomes: [ManagementOutcome<OutreachTemplate>] = [],
    duplicateOutcomes: [ManagementOutcome<OutreachTemplate>] = [],
    defaultOutcomes: [ManagementOutcome<OutreachTemplate>] = [],
    deleteOutcomes: [VoidOutcome] = [],
    previewOutcomes: [ManagementOutcome<RenderedEmail>] = [],
    resendOutcomes: [ManagementOutcome<Delivery>] = []
  ) {
    self.campaignPageOutcomes = campaignPageOutcomes
    self.campaignOutcomes = campaignOutcomes
    self.templateListOutcomes = templateListOutcomes
    self.saveOutcomes = saveOutcomes
    self.duplicateOutcomes = duplicateOutcomes
    self.defaultOutcomes = defaultOutcomes
    self.deleteOutcomes = deleteOutcomes
    self.previewOutcomes = previewOutcomes
    self.resendOutcomes = resendOutcomes
  }

  func listCampaigns(cursor: String?) async throws -> CampaignPage {
    campaignPageCalls.append(cursor)
    return try await resolve(campaignPageOutcomes.removeFirst())
  }

  func campaign(id: UUID) async throws -> OutreachCampaign {
    campaignCalls.append(id)
    return try await resolve(campaignOutcomes.removeFirst())
  }

  func listTemplates() async throws -> [OutreachTemplate] {
    try await resolve(templateListOutcomes.removeFirst())
  }

  func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    saveCalls.append(draft)
    return try await resolve(saveOutcomes.removeFirst())
  }

  func duplicateTemplate(id: UUID) async throws -> OutreachTemplate {
    duplicateCalls.append(id)
    return try await resolve(duplicateOutcomes.removeFirst())
  }

  func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate {
    defaultCalls.append(id)
    return try await resolve(defaultOutcomes.removeFirst())
  }

  func deleteTemplate(id: UUID) async throws {
    deleteCalls.append(id)
    switch deleteOutcomes.removeFirst() {
    case .success: return
    case .failure(let error): throw error
    }
  }

  func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    previewCalls.append(draft)
    return try await resolve(previewOutcomes.removeFirst())
  }

  func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    resendCalls.append(.init(id: id, key: idempotencyKey))
    return try await resolve(resendOutcomes.removeFirst())
  }

  private func resolve<Value: Sendable>(_ outcome: ManagementOutcome<Value>) async throws -> Value {
    switch outcome {
    case .value(let value): return value
    case .failure(let error): throw error
    case .gated(let gate): return try await gate.wait().get()
    }
  }
}

extension APIService {
  fileprivate func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  fileprivate func listJobs(changedAfter: String?, status: JobStatus?) async throws
    -> JobChangePage
  {
    fatalError("unused")
  }
  fileprivate func createAnalysisJob(
    _ request: AnalysisRequest, idempotencyKey: String
  ) async throws
    -> AnalysisSubmission
  { fatalError("unused") }
  fileprivate func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
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
  fileprivate func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    fatalError("unused")
  }
  fileprivate func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  { fatalError("unused") }
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

private func waitUntil(_ condition: @escaping @Sendable () async -> Bool) async -> Bool {
  for _ in 0..<1_000 {
    if await condition() { return true }
    await Task.yield()
  }
  return await condition()
}

private func id(_ suffix: Int) -> UUID {
  UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))!
}

private func metrics() -> CampaignMetrics {
  CampaignMetrics(
    sentCreators: 4, accepted: 1, declined: 1, noResponse: 2, failed: 1,
    responseRate: 0.5)
}

private func game(id: UUID = id(900), name: String) -> CampaignGame {
  CampaignGame(
    id: id, name: name, steamAppID: "730", steamURL: "https://store.steampowered.com/app/730",
    coverURL: nil)
}

private func campaignSummary(id identifier: UUID, game name: String) -> CampaignSummary {
  CampaignSummary(
    id: identifier, matchTaskID: id(901), game: game(name: name), state: .completed,
    sendBatchCount: 1, metrics: metrics(), createdAt: Date(timeIntervalSince1970: 10),
    latestActivityAt: Date(timeIntervalSince1970: 20))
}

private func campaign(id identifier: UUID, game name: String, deliveries: [Delivery])
  -> OutreachCampaign
{
  let batch = SendBatch(
    id: id(902), campaignID: identifier, matchTaskID: id(901), templateID: id(903),
    templateName: "Default", templateVersion: 1, requestedCreatorIDs: deliveries.map(\.creatorID),
    requestedAt: Date(timeIntervalSince1970: 11), state: .sent, deliveries: deliveries)
  return OutreachCampaign(
    id: identifier, matchTaskID: id(901), game: game(name: name), state: .completed,
    sendBatchCount: 1, metrics: metrics(), createdAt: Date(timeIntervalSince1970: 10),
    latestActivityAt: Date(timeIntervalSince1970: 20), sendBatches: [batch])
}

private func delivery(id identifier: UUID, resends: UUID? = nil) -> Delivery {
  Delivery(
    id: identifier, campaignID: id(60), sendBatchID: id(902), creatorID: id(904),
    creator: OutreachCreator(
      id: id(904), name: "Creator", youtubeChannelID: "UC-demo",
      canonicalURL: "https://youtube.com/channel/UC-demo", avatarURL: nil),
    recipientEmail: "creator@example.test", sendState: .sent, responseState: .noResponse,
    resendsDeliveryID: resends, supersededByDeliveryID: nil, isCurrent: true,
    templateName: "Default", templateVersion: 1, renderedSubject: "Subject",
    renderedMarkdown: "Body", renderedHTML: "<p>Body</p>", senderName: "Sender",
    senderAddress: "sender@example.test", replyTo: nil, acceptedLabel: "Yes, I'm in",
    declinedLabel: "No, I'm not interested", smtpFailure: nil, canResend: true,
    createdAt: Date(timeIntervalSince1970: 12), sendingAt: nil,
    sentAt: Date(timeIntervalSince1970: 13), failedAt: nil, respondedAt: nil,
    supersededAt: nil)
}

private func template(
  id: UUID,
  name: String,
  subject: String = "Hello {{creator_name}}",
  body: String = "Play {{game_name}}",
  isDefault: Bool,
  version: Int = 1
) -> OutreachTemplate {
  OutreachTemplate(
    id: id, name: name, version: version, subjectTemplate: subject, bodyMarkdown: body,
    acceptedLabel: "Yes, I'm in", declinedLabel: "No, I'm not interested",
    isDefault: isDefault, createdAt: Date(timeIntervalSince1970: 1),
    updatedAt: Date(timeIntervalSince1970: TimeInterval(version + 1)))
}

extension TemplateDraft {
  fileprivate init(template: OutreachTemplate) {
    self.init(
      id: template.id, name: template.name, subjectTemplate: template.subjectTemplate,
      bodyMarkdown: template.bodyMarkdown, acceptedLabel: template.acceptedLabel,
      declinedLabel: template.declinedLabel)
  }
}
