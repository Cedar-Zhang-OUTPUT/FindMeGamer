import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct ClientVerticalSliceTests {
  @MainActor
  @Test func realModelsCompleteAnalyzeMatchComposeAndCampaignFlow() async {
    let api = VerticalSliceAPI()
    let keys = TestKeySequence([
      "17000000-0000-4000-8000-000000000001",
      "17000000-0000-4000-8000-000000000002",
      "17000000-0000-4000-8000-000000000003",
    ])
    let coordinator = ClientCoordinator(
      api: api,
      apiBaseURL: "https://workspace.example.test",
      appVersion: "17.0-test",
      appearanceStore: MemoryAppearanceStore(),
      idempotencyKey: keys.next)

    await coordinator.loadInitialData()

    #expect(coordinator.library.selectedType == .creator)
    #expect(coordinator.library.items.map(\.id) == [fixtureID(10)])
    #expect(coordinator.settings.smtpStatus?.configured == true)
    #expect(coordinator.settings.connectionStatus(for: .steam)?.configured == true)
    #expect(coordinator.settings.connectionStatus(for: .youtube)?.configured == true)
    #expect(coordinator.settings.connectionStatus(for: .deepSeek)?.configured == true)
    #expect(
      coordinator.settings.sharedSettings
        == SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14))
    #expect(coordinator.settings.creatorActivity.latestAnalysis == fixtureDate(10))

    coordinator.analyze.targetType = .creator
    coordinator.analyze.urlText = "https://youtube.com/@alpha-plays"
    await coordinator.analyze.submit()
    #expect(coordinator.analyze.jobs.map(\.status) == [.queued])

    let profileCallsBeforeAnalysis = await api.profileListCallCount
    let matchCallsBeforeAnalysis = await api.matchCallCount
    await coordinator.consume(
      JobChangeBatch(
        changes: [.analysis(successfulAnalysisJob())],
        affectedProfileIDs: [fixtureID(11)],
        affectedMatchTaskIDs: [],
        affectedGameIDs: [],
        hasActiveJobs: false))

    #expect(coordinator.analyze.jobs.first?.status == .succeeded)
    #expect(coordinator.library.items.map(\.id) == [fixtureID(10), fixtureID(11)])
    #expect(coordinator.library.items.compactMap(creatorName) == ["Legacy Creator", "Alpha Plays"])
    #expect(await api.profileListCallCount == profileCallsBeforeAnalysis + 1)
    #expect(await api.matchCallCount == matchCallsBeforeAnalysis)

    await coordinator.match.loadGames()
    #expect(coordinator.match.games.map(\.name) == ["Signal Quest"])
    coordinator.match.selectedGame = coordinator.match.games.first
    await coordinator.match.submit()
    #expect(coordinator.match.tasks.first?.status == .queued)

    await coordinator.consume(matchCompletionBatch())
    await coordinator.match.openResult(id: fixtureID(30))
    guard case .available(let result) = coordinator.match.resultState else {
      Issue.record("Expected the real Match model to expose an available result")
      return
    }
    #expect(result.recommendedMatches.map(\.id) == [fixtureID(11)])
    #expect(result.otherMatches.map(\.id) == [fixtureID(12)])
    #expect(result.recommendedMatches.map(\.label) == [.strong])
    #expect(result.otherMatches.map(\.label) == [.limited])

    let orderedCreatorIDs = [fixtureID(12), fixtureID(11)]
    await coordinator.composer.load(matchID: result.id, creatorIDs: orderedCreatorIDs)
    #expect(coordinator.composer.selectedTemplate?.name == "Default Outreach")
    #expect(coordinator.composer.previews.map(\.creatorID) == orderedCreatorIDs)
    #expect(
      coordinator.composer.previews.map(\.subject) == ["Hello Beta Studio", "Hello Alpha Plays"])
    #expect(coordinator.outreach.campaigns.isEmpty)

    await coordinator.composer.confirmSend()
    guard let accepted = coordinator.composer.acceptedBatch else {
      Issue.record("Expected one accepted Send Batch")
      return
    }
    #expect(coordinator.outreach.campaigns.isEmpty)
    await coordinator.sendBatchAccepted(accepted)

    #expect(coordinator.outreach.campaigns.count == 1)
    #expect(coordinator.outreach.campaigns.first?.metrics.sentCreators == 1)
    #expect(await api.sendCalls.count == 1)
    #expect(await api.sendCalls.first?.draft.creatorIDs == orderedCreatorIDs)
    #expect(await api.sendCalls.first?.key == "17000000-0000-4000-8000-000000000003")
    #expect(accepted.deliveries.isEmpty)
  }

  @MainActor
  @Test func recoveryPreservesDraftAndRoutingWakesOnlyAffectedModels() async {
    let api = VerticalSliceAPI()
    let coordinator = ClientCoordinator(
      api: api,
      apiBaseURL: "https://workspace.example.test",
      appVersion: "17.0-test",
      appearanceStore: MemoryAppearanceStore())
    await coordinator.loadInitialData()

    coordinator.settings.updateSMTPDraft(
      host: "edited.smtp.example.test",
      port: 465,
      encryption: .tls,
      username: "sender@example.test",
      password: "canary-password",
      fromName: "Edited Sender",
      replyTo: "reply@example.test",
      emailsPerMinute: 12)
    let writesBeforeRecovery = await api.settingsWriteCount

    await coordinator.workspaceConnectionChanged(isOnline: false, visible: .settings)
    #expect(coordinator.settings.workspaceStatus == "Offline")
    await coordinator.workspaceConnectionChanged(isOnline: true, visible: .settings)

    #expect(coordinator.settings.workspaceStatus == "Connected")
    #expect(coordinator.settings.smtpHost == "edited.smtp.example.test")
    #expect(coordinator.settings.smtpPassword == "canary-password")
    #expect(coordinator.settings.smtpIsDirty)
    #expect(await api.settingsWriteCount == writesBeforeRecovery)

    let unrelated = JobChangeBatch(
      changes: [], affectedProfileIDs: [], affectedMatchTaskIDs: [], affectedGameIDs: [],
      hasActiveJobs: false)
    #expect(ClientBatchRouting(batch: unrelated) == .analyzeOnly)
    let profileCalls = await api.profileListCallCount
    let matchCalls = await api.matchCallCount
    await coordinator.consume(unrelated)
    #expect(await api.profileListCallCount == profileCalls)
    #expect(await api.matchCallCount == matchCalls)

    let profileBatch = JobChangeBatch(
      changes: [.analysis(successfulAnalysisJob())],
      affectedProfileIDs: [fixtureID(11)], affectedMatchTaskIDs: [], affectedGameIDs: [],
      hasActiveJobs: false)
    #expect(
      ClientBatchRouting(batch: profileBatch) == .init(refreshLibrary: true, refreshMatch: false))

    let matchBatch = matchCompletionBatch()
    #expect(
      ClientBatchRouting(batch: matchBatch) == .init(refreshLibrary: false, refreshMatch: true))
  }
}

private actor VerticalSliceAPI: APIService {
  struct SendCall: Sendable, Equatable {
    let draft: SendBatchDraft
    let key: String
  }

  private var analyzedAlpha = false
  private var campaigns: [CampaignSummary] = []
  private(set) var profileListCallCount = 0
  private(set) var matchCallCount = 0
  private(set) var settingsWriteCount = 0
  private(set) var sendCalls: [SendCall] = []

  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    profileListCallCount += 1
    guard cursor == nil else { return ProfileCardPage(items: [], nextCursor: nil) }
    switch type {
    case .game:
      return ProfileCardPage(items: [.game(gameCard())], nextCursor: nil)
    case .creator:
      var items: [ProfileCard] = [.creator(creatorCard(id: fixtureID(10), name: "Legacy Creator"))]
      if analyzedAlpha {
        items.append(.creator(creatorCard(id: fixtureID(11), name: "Alpha Plays")))
      }
      return ProfileCardPage(items: items, nextCursor: nil)
    }
  }

  func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  {
    #expect(
      request
        == AnalysisRequest(
          url: "https://youtube.com/@alpha-plays", profileType: .creator, mode: .create))
    analyzedAlpha = true
    return .job(queuedAnalysisJob())
  }

  func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    #expect(gameID == fixtureID(20))
    return queuedMatchTask()
  }

  func listMatches(cursor: String?) async throws -> MatchTaskPage {
    MatchTaskPage(items: [], cursor: nil, hasMore: false)
  }

  func match(id: UUID) async throws -> MatchResult {
    matchCallCount += 1
    #expect(id == fixtureID(30))
    return availableMatchResult()
  }

  func listTemplates() async throws -> [OutreachTemplate] {
    [defaultTemplate()]
  }

  func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    request.creatorIDs.map { creatorID in
      let name = creatorID == fixtureID(11) ? "Alpha Plays" : "Beta Studio"
      return RecipientPreview(
        creatorID: creatorID,
        creatorName: name,
        recipientEmail:
          "\(name.lowercased().replacingOccurrences(of: " ", with: "."))@example.test",
        subject: "Hello \(name)",
        markdown: "A server-rendered note for \(name).",
        html: "<p>A server-rendered note for \(name).</p>")
    }
  }

  func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  {
    sendCalls.append(SendCall(draft: request, key: idempotencyKey))
    campaigns = [campaignSummary()]
    return SendBatch(
      id: fixtureID(50),
      campaignID: fixtureID(51),
      matchTaskID: request.matchTaskID,
      templateID: request.templateID,
      templateName: "Default Outreach",
      templateVersion: 1,
      requestedCreatorIDs: request.creatorIDs,
      requestedAt: fixtureDate(50),
      state: .queued,
      deliveries: [])
  }

  func listCampaigns(cursor: String?) async throws -> CampaignPage {
    CampaignPage(items: campaigns, cursor: nil, hasMore: false)
  }

  func smtpSettings() async throws -> SMTPSettingsStatus {
    SMTPSettingsStatus(
      configured: true,
      host: "smtp.example.test",
      port: 587,
      encryption: .startTLS,
      username: "sender@example.test",
      fromName: "Demo Sender",
      replyTo: "reply@example.test",
      emailsPerMinute: 20,
      lastTestStatus: .success,
      lastTestedAt: fixtureDate(2))
  }

  func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    settingsWriteCount += 1
    fatalError("The recovery path must not write Email Settings")
  }

  func sharedSettings() async throws -> SharedSettings {
    SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
  }

  func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    settingsWriteCount += 1
    fatalError("The recovery path must not write Re-analysis Settings")
  }

  func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    ConnectionStatus(
      service: service,
      configured: true,
      lastTestStatus: .success,
      lastTestedAt: fixtureDate(3))
  }
}

extension APIService {
  fileprivate func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  fileprivate func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage
  {
    JobChangePage(items: [], cursor: "initial", hasMore: false, affectedProfileIDs: [])
  }
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
  fileprivate func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func campaign(id: UUID) async throws -> OutreachCampaign { fatalError("unused") }
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
  fileprivate func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
  fileprivate func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws
    -> ConnectionTestResult
  { fatalError("unused") }
  fileprivate func sendSMTPTest(to email: String) async throws -> ConnectionTestResult {
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
private final class MemoryAppearanceStore: AppearancePreferenceStoring {
  private var values: [String: String] = [:]

  func string(forKey key: String) -> String? { values[key] }
  func set(_ value: String, forKey key: String) { values[key] = value }
}

private final class TestKeySequence: @unchecked Sendable {
  let values: [String]
  private let lock = NSLock()
  private var index = 0

  init(_ values: [String]) {
    self.values = values
  }

  func next() -> String {
    lock.lock()
    defer { lock.unlock() }
    defer { index += 1 }
    return values[index]
  }
}

private func fixtureID(_ suffix: Int) -> UUID {
  UUID(uuidString: String(format: "17000000-0000-4000-8000-%012d", suffix))!
}

private func fixtureDate(_ seconds: TimeInterval) -> Date {
  Date(timeIntervalSince1970: seconds)
}

private func creatorName(_ card: ProfileCard) -> String? {
  guard case .creator(let creator) = card else { return nil }
  return creator.name
}

private func creatorCard(id: UUID, name: String) -> CreatorProfileCard {
  CreatorProfileCard(
    id: id,
    name: name,
    youtubeChannelID: "UC\(id.uuidString.suffix(8))",
    canonicalURL: "https://youtube.com/channel/UC\(id.uuidString.suffix(8))",
    favorite: false,
    currentFacts: [:],
    brief: [:],
    sourceStatus: [:],
    lastAnalyzedAt: fixtureDate(10),
    nextAnalysisAt: fixtureDate(20),
    contact: CreatorContact(
      email: "creator@example.test",
      availability: .manual,
      source: "manual",
      sourceURL: nil,
      validationState: "valid"))
}

private func gameCard() -> GameProfileCard {
  GameProfileCard(
    id: fixtureID(20),
    name: "Signal Quest",
    steamAppID: "17020",
    canonicalURL: "https://store.steampowered.com/app/17020",
    favorite: true,
    currentFacts: [:],
    brief: [:],
    sourceStatus: [:],
    lastAnalyzedAt: fixtureDate(8),
    nextAnalysisAt: fixtureDate(18))
}

private func queuedAnalysisJob() -> AnalysisJob {
  analysisJob(status: .queued, profileID: nil, updatedAt: fixtureDate(1))
}

private func successfulAnalysisJob() -> AnalysisJob {
  analysisJob(status: .succeeded, profileID: fixtureID(11), updatedAt: fixtureDate(2))
}

private func analysisJob(status: JobStatus, profileID: UUID?, updatedAt: Date) -> AnalysisJob {
  AnalysisJob(
    id: fixtureID(15),
    profileType: .creator,
    canonicalTargetID: "alpha-plays",
    canonicalURL: "https://youtube.com/@alpha-plays",
    mode: .create,
    status: status,
    stage: status == .succeeded ? .finalizing : .fetchingData,
    completedUnits: status == .succeeded ? 1 : 0,
    totalUnits: 1,
    retryable: false,
    correlationID: nil,
    profileID: profileID,
    createdAt: fixtureDate(1),
    updatedAt: updatedAt,
    startedAt: fixtureDate(1),
    completedAt: status == .succeeded ? fixtureDate(2) : nil,
    failure: nil)
}

private func matchGame() -> MatchGameHeader {
  MatchGameHeader(
    id: fixtureID(20),
    name: "Signal Quest",
    steamAppID: "17020",
    canonicalURL: "https://store.steampowered.com/app/17020",
    coverURL: nil)
}

private func queuedMatchTask() -> MatchTask {
  MatchTask(
    id: fixtureID(30),
    game: matchGame(),
    status: .queued,
    stage: .screening,
    completedUnits: 0,
    totalUnits: 2,
    resultCount: 0,
    retryable: false,
    failure: nil,
    correlationID: nil,
    supersedesID: nil,
    createdAt: fixtureDate(30),
    updatedAt: fixtureDate(30),
    startedAt: nil,
    completedAt: nil)
}

private func matchCompletionBatch() -> JobChangeBatch {
  let change = ChangedMatchJob(
    id: fixtureID(30),
    gameID: fixtureID(20),
    status: .succeeded,
    stage: .ranking,
    completedUnits: 2,
    totalUnits: 2,
    resultCount: 2,
    retryable: false,
    failure: nil,
    correlationID: nil,
    supersedesID: nil,
    createdAt: fixtureDate(30),
    updatedAt: fixtureDate(31),
    startedAt: fixtureDate(30),
    completedAt: fixtureDate(31))
  return JobChangeBatch(
    changes: [.match(change)],
    affectedProfileIDs: [],
    affectedMatchTaskIDs: [fixtureID(30)],
    affectedGameIDs: [fixtureID(20)],
    hasActiveJobs: false)
}

private func availableMatchResult() -> MatchResult {
  MatchResult(
    id: fixtureID(30),
    game: matchGame(),
    status: .succeeded,
    stage: .ranking,
    completedUnits: 2,
    totalUnits: 2,
    resultCount: 2,
    retryable: false,
    failure: nil,
    correlationID: nil,
    supersedesID: nil,
    createdAt: fixtureDate(30),
    updatedAt: fixtureDate(31),
    startedAt: fixtureDate(30),
    completedAt: fixtureDate(31),
    state: .available,
    recommendedMatches: [
      candidate(id: fixtureID(11), name: "Alpha Plays", group: .recommended, label: .strong)
    ],
    otherMatches: [
      candidate(id: fixtureID(12), name: "Beta Studio", group: .other, label: .limited)
    ])
}

private func candidate(id: UUID, name: String, group: MatchGroup, label: MatchLabel)
  -> MatchCandidate
{
  MatchCandidate(
    creator: MatchCreatorCard(
      id: id,
      name: name,
      youtubeChannelID: "UC\(id.uuidString.suffix(8))",
      canonicalURL: "https://youtube.com/channel/UC\(id.uuidString.suffix(8))",
      favorite: false,
      contactAvailable: true,
      contact: MatchCreatorContact(
        email: "creator@example.test",
        source: "manual",
        sourceURL: nil,
        validationState: "valid"),
      avatarURL: nil,
      performanceSummary: "Consistent recent views",
      subscriberCount: 120_000,
      recentAverageViews: 42_000,
      recentMedianViews: 38_000),
    group: group,
    label: label,
    dimensionOutcomes: MatchDimensionOutcomes(
      contentFit: "Strong",
      audienceFit: "Strong",
      performanceFit: "Good",
      promotionFit: "Good",
      brandSafety: "Good"),
    reasons: ["Audience overlap"],
    brief: MatchBrief(
      contentFit: MatchBriefDimension(analysis: "Fits the game", evidence: ["Recent videos"]),
      audienceFit: MatchBriefDimension(analysis: "Relevant audience", evidence: ["Channel topics"]),
      performanceFit: MatchBriefDimension(
        analysis: "Steady performance", evidence: ["Recent views"]),
      promotionFit: MatchBriefDimension(analysis: "Open to coverage", evidence: ["Past reviews"]),
      brandSafety: MatchBriefDimension(analysis: "Suitable tone", evidence: ["Public catalog"]),
      strengths: ["Clear presentation"],
      risks: [],
      evidence: ["Public channel data"],
      matchReasons: ["Strong audience fit"]),
    outreach: MatchOutreach(deliveryID: nil, sendState: .notSent, responseState: .pending))
}

private func defaultTemplate() -> OutreachTemplate {
  OutreachTemplate(
    id: fixtureID(40),
    name: "Default Outreach",
    version: 1,
    subjectTemplate: "Hello {{creator_name}}",
    bodyMarkdown: "Would you like to cover {{game_name}}?",
    acceptedLabel: "I'm interested",
    declinedLabel: "Not right now",
    isDefault: true,
    createdAt: fixtureDate(40),
    updatedAt: fixtureDate(41))
}

private func campaignSummary() -> CampaignSummary {
  CampaignSummary(
    id: fixtureID(51),
    matchTaskID: fixtureID(30),
    game: CampaignGame(
      id: fixtureID(20),
      name: "Signal Quest",
      steamAppID: "17020",
      steamURL: "https://store.steampowered.com/app/17020",
      coverURL: nil),
    state: .sending,
    sendBatchCount: 1,
    metrics: CampaignMetrics(
      sentCreators: 1,
      accepted: 0,
      declined: 0,
      noResponse: 1,
      failed: 0,
      responseRate: 0),
    createdAt: fixtureDate(50),
    latestActivityAt: fixtureDate(51))
}
