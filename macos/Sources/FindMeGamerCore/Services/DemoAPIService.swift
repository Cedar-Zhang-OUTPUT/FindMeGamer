import Foundation

actor DemoAPIService: APIService {
  private let scenario: DemoScenario
  private var pendingMatchResults: [UUID: MatchResult] = [:]
  private var scenarioMatchPolls: [UUID: Int] = [:]
  private var scenarioRevision = 0
  private var shouldFailNextPreview: Bool
  private var games: [GameProfile]
  private var creators: [CreatorProfile]
  private var discoveredContactsByCreatorID: [UUID: [CreatorContact]]
  private var analysisJobs: [AnalysisJob]
  private var matches: [MatchResult]
  private var campaigns: [OutreachCampaign]
  private var templates: [OutreachTemplate]
  private var smtp: SMTPSettingsStatus
  private var reanalysis: SharedSettings
  private var connections: [ConnectionService: ConnectionStatus]

  init(scenario: DemoScenario = .normal) {
    self.scenario = scenario
    shouldFailNextPreview = scenario == .qaJourney
    let fixtures = DemoFixtures.make()
    games = scenario == .emptyLibrary ? [] : fixtures.games
    creators = scenario == .emptyLibrary ? [] : fixtures.creators
    discoveredContactsByCreatorID = Dictionary(
      uniqueKeysWithValues: (scenario == .emptyLibrary ? [] : fixtures.creators).map { creator in
        (
          creator.id,
          creator.contacts.filter { $0.availability == .discovered }
        )
      })
    analysisJobs = scenario == .emptyLibrary ? [] : fixtures.analysisJobs
    matches = scenario == .emptyLibrary ? [] : fixtures.matches
    campaigns = scenario == .emptyLibrary ? [] : fixtures.campaigns
    templates = fixtures.templates
    smtp = fixtures.smtp
    reanalysis = fixtures.reanalysis
    connections = fixtures.connections
  }

  func validateSession() async throws -> WorkspaceSession {
    WorkspaceSession(
      workspaceName: "Find Me Gamer Demo",
      apiVersion: "demo-1",
      serviceConnections: Dictionary(
        uniqueKeysWithValues: ConnectionService.allCases.map { ($0.rawValue, true) }))
  }

  func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage {
    advanceScenarioMatches()
    let filtered = analysisJobs.filter { status == nil || $0.status == status }
    let matchChanges = matches.filter {
      scenarioMatchPolls[$0.id] != nil && (status == nil || $0.status == status)
    }.map { result in
      JobChange.match(
        ChangedMatchJob(
          id: result.id, gameID: result.game.id, status: result.status, stage: result.stage,
          completedUnits: result.completedUnits, totalUnits: result.totalUnits,
          resultCount: result.resultCount, retryable: result.retryable, failure: result.failure,
          correlationID: result.correlationID, supersedesID: result.supersedesID,
          createdAt: result.createdAt, updatedAt: result.updatedAt,
          startedAt: result.startedAt, completedAt: result.completedAt))
    }
    return JobChangePage(
      items: filtered.map(JobChange.analysis) + matchChanges,
      cursor: scenario == .qaJourney
        ? "demo-\(analysisJobs.count)-\(scenarioRevision)" : "demo-\(analysisJobs.count)",
      hasMore: false,
      affectedProfileIDs: filtered.compactMap(\.profileID))
  }

  func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  {
    if let existing = existingProfile(for: request) {
      return .existingProfile(existing)
    }

    let now = DemoFixtures.date(dayOffset: 0)
    let profileID = UUID()
    let canonicalURL = request.url.trimmingCharacters(in: .whitespacesAndNewlines)
    let targetID = canonicalURL.split(separator: "/").last.map(String.init) ?? profileID.uuidString

    switch request.profileType {
    case .game:
      games.insert(
        DemoFixtures.game(
          id: profileID,
          name: "New Demo Game",
          appID: targetID.filter(\.isNumber).isEmpty ? "demo" : targetID.filter(\.isNumber),
          url: canonicalURL,
          favorite: false,
          summary: "A newly analyzed Game Profile created locally for UI exploration.",
          genres: ["Indie", "Adventure", "Demo"]),
        at: 0)
    case .creator:
      creators.insert(
        DemoFixtures.creator(
          id: profileID,
          name: "New Demo Creator",
          channelID: targetID,
          url: canonicalURL,
          favorite: false,
          subscribers: 42_000,
          focus: ["Indie", "First Look", "Reviews"],
          performance: "Newly analyzed local demo profile."),
        at: 0)
      discoveredContactsByCreatorID[profileID] = creators[0].contacts.filter {
        $0.availability == .discovered
      }
    }

    let job = AnalysisJob(
      id: UUID(),
      profileType: request.profileType,
      canonicalTargetID: targetID,
      canonicalURL: canonicalURL,
      mode: request.mode ?? .create,
      status: .succeeded,
      stage: .finalizing,
      completedUnits: 3,
      totalUnits: 3,
      retryable: false,
      correlationID: "LOCAL-DEMO",
      profileID: profileID,
      createdAt: now,
      updatedAt: now,
      startedAt: now,
      completedAt: now,
      failure: nil)
    analysisJobs.insert(job, at: 0)
    return .job(job)
  }

  func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    guard let job = analysisJobs.first(where: { $0.id == id }) else {
      throw notFound("Analysis job")
    }
    return job
  }

  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    guard cursor == nil else { return ProfileCardPage(items: [], nextCursor: nil) }
    let needle = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    let cards: [ProfileCard]
    switch type {
    case .game:
      cards =
        games
        .filter { profile in
          (!onlyCollection || profile.favorite)
            && (needle.isEmpty
              || profile.name.lowercased().contains(needle)
              || profile.steamAppID.lowercased().contains(needle))
        }
        .prefix(max(0, limit))
        .map { .game(DemoFixtures.card($0)) }
    case .creator:
      cards =
        creators
        .filter { profile in
          (!onlyCollection || profile.favorite)
            && (needle.isEmpty
              || profile.name.lowercased().contains(needle)
              || profile.youtubeChannelID.lowercased().contains(needle))
        }
        .prefix(max(0, limit))
        .map { .creator(DemoFixtures.card($0)) }
    }
    return ProfileCardPage(items: cards, nextCursor: nil)
  }

  func profile(type: ProfileType, id: UUID) async throws -> Profile {
    switch type {
    case .game:
      guard let value = games.first(where: { $0.id == id }) else { throw notFound("Game") }
      return .game(value)
    case .creator:
      guard let value = creators.first(where: { $0.id == id }) else {
        throw notFound("Creator")
      }
      return .creator(value)
    }
  }

  func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws -> ProfileCard {
    switch type {
    case .game:
      guard let index = games.firstIndex(where: { $0.id == id }) else { throw notFound("Game") }
      games[index] = DemoFixtures.replacingFavorite(games[index], favorite: favorite)
      return .game(DemoFixtures.card(games[index]))
    case .creator:
      guard let index = creators.firstIndex(where: { $0.id == id }) else {
        throw notFound("Creator")
      }
      creators[index] = DemoFixtures.replacingFavorite(creators[index], favorite: favorite)
      return .creator(DemoFixtures.card(creators[index]))
    }
  }

  func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  {
    guard let index = creators.firstIndex(where: { $0.id == id }) else {
      throw notFound("Creator")
    }
    let old = creators[index]
    let normalized = email?.trimmingCharacters(in: .whitespacesAndNewlines)
    let previousManualContact = old.contacts.first { $0.availability == .manual }
    let manualContact =
      normalized.flatMap { value -> CreatorContact? in
        guard !value.isEmpty else { return nil }
        return CreatorContact(
          email: value, availability: .manual, source: "manual", sourceURL: nil,
          validationState: "unverified", purpose: previousManualContact?.purpose)
      }
    let canonicalDiscoveredContacts =
      discoveredContactsByCreatorID[id]
      ?? old.contacts.filter { $0.availability == .discovered }
    discoveredContactsByCreatorID[id] = canonicalDiscoveredContacts
    let visibleDiscoveredContacts = canonicalDiscoveredContacts.filter {
      guard let manualContact else { return true }
      return $0.email.caseInsensitiveCompare(manualContact.email) != .orderedSame
    }
    let contacts =
      manualContact.map { [$0] + visibleDiscoveredContacts } ?? canonicalDiscoveredContacts
    let primaryContact = manualContact ?? canonicalDiscoveredContacts.first
    let updated = CreatorProfile(
      id: old.id, name: old.name, youtubeChannelID: old.youtubeChannelID,
      canonicalURL: old.canonicalURL, favorite: old.favorite,
      currentFacts: old.currentFacts, brief: old.brief, sourceStatus: old.sourceStatus,
      lastAnalyzedAt: old.lastAnalyzedAt, nextAnalysisAt: old.nextAnalysisAt,
      contact: primaryContact, manualNotes: notes, analysis: old.analysis,
      modelMetadata: old.modelMetadata, promptMetadata: old.promptMetadata,
      contacts: contacts)
    creators[index] = updated
    return updated
  }

  func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    guard let game = games.first(where: { $0.id == gameID }) else { throw notFound("Game") }
    let result = DemoFixtures.match(
      id: UUID(), game: game, creators: Array(creators.prefix(5)), dayOffset: 0)
    if scenario == .qaJourney {
      pendingMatchResults[result.id] = result
      scenarioMatchPolls[result.id] = 0
      let queued = scenarioSnapshot(result, poll: -1)
      matches.insert(queued, at: 0)
      return DemoFixtures.task(queued)
    } else {
      matches.insert(result, at: 0)
      return DemoFixtures.task(result)
    }
  }

  /// The local scenario advances only when the existing job poller asks for the next snapshot.
  /// Pending work has unknown units (0/0), so no pretend completion percentage is exposed.
  private func advanceScenarioMatches() {
    guard scenario == .qaJourney else { return }
    for id in Array(pendingMatchResults.keys) {
      guard let completed = pendingMatchResults[id],
        let index = matches.firstIndex(where: { $0.id == id })
      else { continue }
      let poll = scenarioMatchPolls[id] ?? 0
      matches[index] = scenarioSnapshot(completed, poll: poll)
      scenarioMatchPolls[id] = poll + 1
      scenarioRevision += 1
      if poll >= 3 { pendingMatchResults[id] = nil }
    }
  }

  private func scenarioSnapshot(_ result: MatchResult, poll: Int) -> MatchResult {
    let completed = poll >= 3
    let status: JobStatus = completed ? .succeeded : (poll <= 0 ? .queued : .running)
    let stage: MatchStage = completed ? .ranking : (poll == 2 ? .pairwise : .screening)
    let updated = result.createdAt.addingTimeInterval(Double(poll + 1))
    return MatchResult(
      id: result.id, game: result.game, status: status, stage: stage,
      completedUnits: completed ? result.completedUnits : 0,
      totalUnits: completed ? result.totalUnits : 0,
      resultCount: completed ? result.resultCount : 0,
      retryable: false, failure: nil, correlationID: "LOCAL-DEMO-QA",
      supersedesID: nil, createdAt: result.createdAt, updatedAt: updated,
      startedAt: status == .queued ? nil : result.createdAt.addingTimeInterval(2),
      completedAt: completed ? updated : nil,
      state: completed ? result.state : .pending,
      recommendedMatches: completed ? result.recommendedMatches : [],
      otherMatches: completed ? result.otherMatches : [])
  }

  func listMatches(cursor: String?) async throws -> MatchTaskPage {
    guard cursor == nil else { return MatchTaskPage(items: [], cursor: nil, hasMore: false) }
    return MatchTaskPage(
      items: matches.sorted { $0.createdAt > $1.createdAt }.map(DemoFixtures.task),
      cursor: nil,
      hasMore: false)
  }

  func match(id: UUID) async throws -> MatchResult {
    guard let result = matches.first(where: { $0.id == id }) else { throw notFound("Match") }
    return DemoFixtures.refreshingCreators(in: result, from: creators)
  }

  func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    DemoFixtures.task(try await match(id: id))
  }

  func listCampaigns(cursor: String?) async throws -> CampaignPage {
    guard cursor == nil else { return CampaignPage(items: [], cursor: nil, hasMore: false) }
    return CampaignPage(
      items: campaigns.sorted { $0.latestActivityAt > $1.latestActivityAt }
        .map(DemoFixtures.summary),
      cursor: nil,
      hasMore: false)
  }

  func campaign(id: UUID) async throws -> OutreachCampaign {
    guard let campaign = campaigns.first(where: { $0.id == id }) else {
      throw notFound("Campaign")
    }
    return campaign
  }

  func listTemplates() async throws -> [OutreachTemplate] {
    templates.sorted { left, right in
      if left.isDefault != right.isDefault { return left.isDefault }
      return left.name.localizedCaseInsensitiveCompare(right.name) == .orderedAscending
    }
  }

  func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    let now = DemoFixtures.date(dayOffset: 0)
    if let id = draft.id, let index = templates.firstIndex(where: { $0.id == id }) {
      let current = templates[index]
      let updated = OutreachTemplate(
        id: id, name: draft.name, version: current.version + 1,
        subjectTemplate: draft.subjectTemplate, bodyMarkdown: draft.bodyMarkdown,
        acceptedLabel: draft.acceptedLabel ?? current.acceptedLabel,
        declinedLabel: draft.declinedLabel ?? current.declinedLabel,
        isDefault: current.isDefault, createdAt: current.createdAt, updatedAt: now)
      templates[index] = updated
      return updated
    }
    let created = OutreachTemplate(
      id: UUID(), name: draft.name, version: 1,
      subjectTemplate: draft.subjectTemplate, bodyMarkdown: draft.bodyMarkdown,
      acceptedLabel: draft.acceptedLabel ?? "Yes, I'm in",
      declinedLabel: draft.declinedLabel ?? "No, I'm not interested",
      isDefault: templates.isEmpty, createdAt: now, updatedAt: now)
    templates.append(created)
    return created
  }

  func duplicateTemplate(id: UUID) async throws -> OutreachTemplate {
    guard let source = templates.first(where: { $0.id == id }) else {
      throw notFound("Template")
    }
    let now = DemoFixtures.date(dayOffset: 0)
    let copy = OutreachTemplate(
      id: UUID(), name: "\(source.name) Copy", version: 1,
      subjectTemplate: source.subjectTemplate, bodyMarkdown: source.bodyMarkdown,
      acceptedLabel: source.acceptedLabel, declinedLabel: source.declinedLabel,
      isDefault: false, createdAt: now, updatedAt: now)
    templates.append(copy)
    return copy
  }

  func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate {
    guard templates.contains(where: { $0.id == id }) else { throw notFound("Template") }
    templates = templates.map { DemoFixtures.replacingDefault($0, isDefault: $0.id == id) }
    return templates.first(where: { $0.id == id })!
  }

  func deleteTemplate(id: UUID) async throws {
    guard let index = templates.firstIndex(where: { $0.id == id }) else {
      throw notFound("Template")
    }
    guard templates.count > 1 else {
      throw APIError(
        code: "template_last_remaining",
        message: "The only remaining Template cannot be deleted.",
        retryable: false)
    }
    guard !templates[index].isDefault else {
      throw APIError(
        code: "template_default_delete_forbidden",
        message: "Choose another default Template before deleting this one.",
        retryable: false)
    }
    templates.remove(at: index)
  }

  func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    let subject = DemoFixtures.render(
      draft.subjectTemplate, creator: "Tactical Cedar", game: "Neon Harbor")
    let markdown = DemoFixtures.render(
      draft.bodyMarkdown, creator: "Tactical Cedar", game: "Neon Harbor")
    return RenderedEmail(
      subject: subject, markdown: markdown,
      html: DemoEmailHTMLRenderer.render(markdown))
  }

  func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    guard (1...30).contains(request.creatorIDs.count),
      Set(request.creatorIDs).count == request.creatorIDs.count,
      request.recipientSelections.count <= 30
    else {
      throw APIError(
        code: "request_invalid",
        message: "Creator IDs must be non-empty, unique, and within the supported batch size.",
        retryable: false)
    }
    let result = try await match(id: request.matchTaskID)
    let matchCreatorIDs = Set(
      (result.recommendedMatches + result.otherMatches).map(\.id)
    )
    guard Set(request.creatorIDs).isSubset(of: matchCreatorIDs) else {
      throw APIError(
        code: "creator_not_in_match",
        message: "Every Creator must belong to the Match result.",
        retryable: false)
    }
    let selectedCreatorIDs = request.recipientSelections.map(\.creatorID)
    guard Set(selectedCreatorIDs).count == selectedCreatorIDs.count,
      Set(selectedCreatorIDs).isSubset(of: Set(request.creatorIDs))
    else {
      throw APIError(
        code: "recipient_email_selection_invalid",
        message: "Every recipient selection must belong to one requested Creator.",
        retryable: false)
    }
    guard
      let template = request.templateID.flatMap({ id in templates.first { $0.id == id } })
        ?? templates.first(where: \.isDefault)
        ?? templates.first
    else {
      throw APIError(
        code: "template_required",
        message: "Create an Outreach Template before previewing a send.",
        retryable: false)
    }
    let previews = try request.creatorIDs.map { id in
      guard let creator = creators.first(where: { $0.id == id }) else {
        throw notFound("Creator")
      }
      let subjectSource = request.subjectOverride ?? template.subjectTemplate
      let bodySource = request.bodyMarkdownOverride ?? template.bodyMarkdown
      let subject = DemoFixtures.render(
        subjectSource, creator: creator.name, game: result.game.name)
      let markdown = DemoFixtures.render(bodySource, creator: creator.name, game: result.game.name)
      return RecipientPreview(
        creatorID: creator.id, creatorName: creator.name,
        recipientEmail: try recipientEmail(for: creator, request: request),
        subject: subject, markdown: markdown,
        html: DemoEmailHTMLRenderer.render(markdown))
    }
    if shouldFailNextPreview {
      shouldFailNextPreview = false
      throw APIError(
        code: "demo_preview_retry",
        message:
          "Local Demo: preview failed once to test recovery. Your draft is kept; choose Try Again.",
        retryable: true)
    }
    return previews
  }

  private func recipientEmail(
    for creator: CreatorProfile,
    request: SendBatchDraft
  ) throws -> String {
    let contacts = creator.contacts.filter {
      !$0.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
    guard !contacts.isEmpty else {
      throw APIError(
        code: "recipient_email_unavailable",
        message: "Every Creator must have an active email address.",
        retryable: false)
    }

    let requestedEmail = request.recipientSelections.first {
      $0.creatorID == creator.id
    }?.email
    guard requestedEmail != nil || contacts.count == 1 else {
      throw APIError(
        code: "recipient_email_selection_required",
        message: "Select exactly one active email for every Creator with multiple emails.",
        retryable: false)
    }
    guard let requestedEmail else { return contacts[0].email }
    guard
      let selected = contacts.first(where: {
        $0.email.caseInsensitiveCompare(requestedEmail) == .orderedSame
      })
    else {
      throw APIError(
        code: "recipient_email_selection_invalid",
        message: "The selected email is not active for this Creator.",
        retryable: false)
    }
    return selected.email
  }

  func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  {
    let previews = try await previewSendBatch(request)
    let result = try await match(id: request.matchTaskID)
    let template =
      request.templateID.flatMap { id in templates.first { $0.id == id } }
      ?? templates.first(where: \.isDefault)
    let campaignID = UUID()
    let batchID = UUID()
    let now = DemoFixtures.date(dayOffset: 0)
    let deliveries = previews.map { preview in
      Delivery(
        id: UUID(), campaignID: campaignID, sendBatchID: batchID,
        creatorID: preview.creatorID,
        creator: DemoFixtures.outreachCreator(
          creators.first(where: { $0.id == preview.creatorID })!),
        recipientEmail: preview.recipientEmail, sendState: .sent, responseState: .pending,
        resendsDeliveryID: nil, supersededByDeliveryID: nil, isCurrent: true,
        templateName: template?.name, templateVersion: template?.version,
        renderedSubject: preview.subject, renderedMarkdown: preview.markdown,
        renderedHTML: preview.html, senderName: "Find Me Gamer Demo",
        senderAddress: "demo@example.test", replyTo: "demo@example.test",
        acceptedLabel: template?.acceptedLabel, declinedLabel: template?.declinedLabel,
        smtpFailure: nil, canResend: false, createdAt: now, sendingAt: now, sentAt: now,
        failedAt: nil, respondedAt: nil, supersededAt: nil)
    }
    let batch = SendBatch(
      id: batchID, campaignID: campaignID, matchTaskID: result.id,
      templateID: template?.id, templateName: template?.name,
      templateVersion: template?.version, requestedCreatorIDs: request.creatorIDs,
      requestedAt: now, state: .sent, deliveries: deliveries)
    let metrics = CampaignMetrics(
      sentCreators: deliveries.count, accepted: 0, declined: 0,
      noResponse: deliveries.count, failed: 0, responseRate: 0)
    campaigns.insert(
      OutreachCampaign(
        id: campaignID, matchTaskID: result.id,
        game: DemoFixtures.campaignGame(result.game), state: .completed,
        sendBatchCount: 1, metrics: metrics, createdAt: now,
        latestActivityAt: now, sendBatches: [batch]),
      at: 0)
    if let index = matches.firstIndex(where: { $0.id == result.id }) {
      matches[index] = DemoFixtures.recordingDeliveries(deliveries, in: matches[index])
    }
    return batch
  }

  func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    for campaign in campaigns {
      for batch in campaign.sendBatches {
        if let source = batch.deliveries.first(where: { $0.id == id }) {
          return Delivery(
            id: UUID(), campaignID: source.campaignID, sendBatchID: source.sendBatchID,
            creatorID: source.creatorID, creator: source.creator,
            recipientEmail: source.recipientEmail, sendState: .sent,
            responseState: .pending, resendsDeliveryID: source.id,
            supersededByDeliveryID: nil, isCurrent: true,
            templateName: source.templateName, templateVersion: source.templateVersion,
            renderedSubject: source.renderedSubject, renderedMarkdown: source.renderedMarkdown,
            renderedHTML: source.renderedHTML, senderName: source.senderName,
            senderAddress: source.senderAddress, replyTo: source.replyTo,
            acceptedLabel: source.acceptedLabel, declinedLabel: source.declinedLabel,
            smtpFailure: nil, canResend: false,
            createdAt: DemoFixtures.date(dayOffset: 0),
            sendingAt: DemoFixtures.date(dayOffset: 0),
            sentAt: DemoFixtures.date(dayOffset: 0), failedAt: nil,
            respondedAt: nil, supersededAt: nil)
        }
      }
    }
    throw notFound("Delivery")
  }

  func smtpSettings() async throws -> SMTPSettingsStatus { smtp }

  func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    smtp = SMTPSettingsStatus(
      configured: true, host: draft.host, port: draft.port ?? 465,
      encryption: draft.encryption ?? .tls, username: draft.username,
      fromName: draft.fromName, replyTo: draft.replyTo,
      emailsPerMinute: draft.emailsPerMinute ?? 10,
      lastTestStatus: .notTested, lastTestedAt: nil)
    return smtp
  }

  func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws -> ConnectionTestResult {
    ConnectionTestResult(
      succeeded: true, status: .success, testedAt: DemoFixtures.date(dayOffset: 0))
  }

  func sendSMTPTest(to email: String) async throws -> ConnectionTestResult {
    ConnectionTestResult(
      succeeded: true, status: .success, testedAt: DemoFixtures.date(dayOffset: 0))
  }

  func sharedSettings() async throws -> SharedSettings { reanalysis }

  func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    reanalysis = SharedSettings(
      gameIntervalDays: max(1, draft.gameIntervalDays),
      creatorIntervalDays: min(30, max(1, draft.creatorIntervalDays)))
    return reanalysis
  }

  func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    connections[service]
      ?? ConnectionStatus(
        service: service, configured: false, lastTestStatus: .notTested,
        lastTestedAt: nil)
  }

  func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  {
    let status = ConnectionStatus(
      service: service, configured: !secret.isEmpty, lastTestStatus: .notTested,
      lastTestedAt: nil)
    connections[service] = status
    return status
  }

  func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult {
    let result = ConnectionTestResult(
      succeeded: true, status: .success, testedAt: DemoFixtures.date(dayOffset: 0))
    connections[service] = ConnectionStatus(
      service: service, configured: true, lastTestStatus: .success,
      lastTestedAt: result.testedAt)
    return result
  }

  private func existingProfile(for request: AnalysisRequest) -> ExistingProfile? {
    switch request.profileType {
    case .game:
      return games.first(where: { $0.canonicalURL == request.url }).map {
        ExistingProfile(
          profileID: $0.id, profileType: .game,
          canonicalTargetID: $0.steamAppID, canonicalURL: $0.canonicalURL)
      }
    case .creator:
      return creators.first(where: { $0.canonicalURL == request.url }).map {
        ExistingProfile(
          profileID: $0.id, profileType: .creator,
          canonicalTargetID: $0.youtubeChannelID, canonicalURL: $0.canonicalURL)
      }
    }
  }

  private func notFound(_ item: String) -> APIError {
    APIError(
      code: "not_found", message: "\(item) was not found in local demo data.", retryable: false)
  }
}

private struct DemoFixtures {
  let games: [GameProfile]
  let creators: [CreatorProfile]
  let analysisJobs: [AnalysisJob]
  let matches: [MatchResult]
  let campaigns: [OutreachCampaign]
  let templates: [OutreachTemplate]
  let smtp: SMTPSettingsStatus
  let reanalysis: SharedSettings
  let connections: [ConnectionService: ConnectionStatus]

  static func make() -> DemoFixtures {
    let games = [
      game(
        id: id(101), name: "Neon Harbor", appID: "2864100",
        url: "https://store.steampowered.com/app/2864100/Neon_Harbor/",
        favorite: true,
        summary: "Build a floating city, route its power, and survive electric storms.",
        genres: ["Strategy", "Simulation", "Co-op"]),
      game(
        id: id(102), name: "Mossbound", appID: "2917020",
        url: "https://store.steampowered.com/app/2917020/Mossbound/",
        favorite: false,
        summary: "A gentle exploration adventure about restoring a forgotten forest.",
        genres: ["Cozy", "Adventure", "Puzzle"]),
      game(
        id: id(103), name: "Iron Chorus", appID: "3038110",
        url: "https://store.steampowered.com/app/3038110/Iron_Chorus/",
        favorite: false,
        summary: "Command a rebel fleet through tactical battles and branching choices.",
        genres: ["Tactics", "Roguelite", "Sci-fi"]),
    ]
    let creators = [
      creator(
        id: id(201), name: "Tactical Cedar", channelID: "UCTacticalCedarDemo",
        url: "https://youtube.com/@tacticalcedar", favorite: true,
        subscribers: 184_000, focus: ["Strategy", "Tactics", "Reviews"],
        performance: "Reliable 45K–70K views on strategy deep dives.",
        additionalContacts: [
          CreatorContact(
            email: "tacticalcedar.press@example.test", availability: .discovered,
            source: "public_web_research", sourceURL: "https://tacticalcedar.example/contact",
            validationState: "unverified", purpose: "Press")
        ]),
      creator(
        id: id(202), name: "Indie Orbit", channelID: "UCIndieOrbitDemo",
        url: "https://youtube.com/@indieorbit", favorite: true,
        subscribers: 322_000, focus: ["Indie", "First Look", "Discovery"],
        performance: "Strong discovery reach with consistent weekly uploads."),
      creator(
        id: id(203), name: "Cozy Circuit", channelID: "UCCozyCircuitDemo",
        url: "https://youtube.com/@cozycircuit", favorite: false,
        subscribers: 96_000, focus: ["Cozy", "Simulation", "Streams"],
        performance: "Highly engaged audience for relaxed management games."),
      creator(
        id: id(204), name: "Pixel Forge", channelID: "UCPixelForgeDemo",
        url: "https://youtube.com/@pixelforge", favorite: false,
        subscribers: 510_000, focus: ["Reviews", "Action", "Indie"],
        performance: "Broad reach with polished edited reviews."),
      creator(
        id: id(205), name: "Rogue Signal", channelID: "UCRogueSignalDemo",
        url: "https://youtube.com/@roguesignal", favorite: false,
        subscribers: 71_000, focus: ["Roguelite", "Challenge", "Guides"],
        performance: "Smaller channel with above-average audience retention."),
      creator(
        id: id(206), name: "The Strategy Desk", channelID: "UCStrategyDeskDemo",
        url: "https://youtube.com/@strategydesk", favorite: false,
        subscribers: 245_000, focus: ["Strategy", "Analysis", "PC Gaming"],
        performance: "High-intent PC strategy audience and long-form coverage."),
    ]
    let firstMatch = match(
      id: id(301), game: games[0], creators: Array(creators.prefix(5)), dayOffset: -2)
    let secondMatch = match(
      id: id(302), game: games[1], creators: [creators[2], creators[1], creators[3]],
      dayOffset: -8)
    let template = OutreachTemplate(
      id: id(501), name: "Friendly Introduction", version: 3,
      subjectTemplate: "A game we think {{creator_name}} will enjoy",
      bodyMarkdown:
        "Hi {{creator_name}},\n\nWe think **{{game_name}}** fits your audience. Would you like a key and press kit?\n\n— {{sender_name}}",
      acceptedLabel: "Yes, I'm in", declinedLabel: "No, I'm not interested",
      isDefault: true, createdAt: date(dayOffset: -40), updatedAt: date(dayOffset: -4))
    let followUp = OutreachTemplate(
      id: id(502), name: "Short Follow-up", version: 1,
      subjectTemplate: "Quick follow-up: {{game_name}}",
      bodyMarkdown: "Hi {{creator_name}}, just checking whether this game is a fit for you.",
      acceptedLabel: "Send me details", declinedLabel: "Not this time",
      isDefault: false, createdAt: date(dayOffset: -10), updatedAt: date(dayOffset: -10))
    let campaign = campaignFixture(match: firstMatch, creators: creators, template: template)
    let completedAnalysis = AnalysisJob(
      id: id(601), profileType: .creator, canonicalTargetID: creators[0].youtubeChannelID,
      canonicalURL: creators[0].canonicalURL, mode: .create, status: .succeeded,
      stage: .finalizing, completedUnits: 3, totalUnits: 3, retryable: false,
      correlationID: "LOCAL-DEMO", profileID: creators[0].id,
      createdAt: date(dayOffset: -3), updatedAt: date(dayOffset: -3),
      startedAt: date(dayOffset: -3), completedAt: date(dayOffset: -3), failure: nil)
    let testedAt = date(dayOffset: -1)
    let connections = Dictionary(
      uniqueKeysWithValues: ConnectionService.allCases.map {
        (
          $0,
          ConnectionStatus(
            service: $0, configured: true, lastTestStatus: .success, lastTestedAt: testedAt)
        )
      })
    return DemoFixtures(
      games: games, creators: creators, analysisJobs: [completedAnalysis],
      matches: [firstMatch, secondMatch], campaigns: [campaign],
      templates: [template, followUp],
      smtp: SMTPSettingsStatus(
        configured: true, host: "smtp.demo.example.test", port: 465,
        encryption: .tls, username: "outreach@example.test",
        fromName: "Find Me Gamer Team", replyTo: "outreach@example.test",
        emailsPerMinute: 10, lastTestStatus: .success, lastTestedAt: testedAt),
      reanalysis: SharedSettings(gameIntervalDays: 14, creatorIntervalDays: 7),
      connections: connections)
  }

  static func game(
    id: UUID, name: String, appID: String, url: String, favorite: Bool,
    summary: String, genres: [String]
  ) -> GameProfile {
    let facts: JSONObject = [
      "short_description": .string(summary),
      "genres": .array(genres.map(JSONValue.string)),
      "developers": .array([.string("Northstar Demo Studio")]),
      "publishers": .array([.string("Find Me Gamer Publishing")]),
      "release_date": .string("Coming soon"),
      "platforms": .array([.string("Windows"), .string("macOS")]),
      "supported_languages": .array([.string("English"), .string("Simplified Chinese")]),
    ]
    let brief: JSONObject = [
      "positioning_premise": .string(summary),
      "core_gameplay_loop": .string("Explore, make meaningful choices, and improve each run."),
      "genres": .array(genres.map(JSONValue.string)),
      "themes": .array([.string("Discovery"), .string("Mastery"), .string("Community")]),
      "tone": .string("Inviting, thoughtful, and creator-friendly."),
      "visual_identity": .string("Readable silhouettes with a vivid contemporary palette."),
      "target_audience": .string("PC players who follow thoughtful indie coverage."),
      "key_selling_points": .array([.string("Clear creator hooks"), .string("Replayable systems")]),
      "content_hooks": .array([.string("First impressions"), .string("Challenge runs")]),
      "comparable_games": .array([.string("Against the Storm"), .string("Into the Breach")]),
      "suitable_creator_types": .array([.string("Reviewers"), .string("Strategy specialists")]),
      "promotion_risks": .array([.string("Systems need a concise onboarding explanation")]),
    ]
    let analysis: JSONObject = [
      "short_summary": .string(summary),
      "themes": brief["themes"]!, "tone": brief["tone"]!,
      "key_selling_points": brief["key_selling_points"]!,
      "core_gameplay_loop": brief["core_gameplay_loop"]!,
      "comparable_games": brief["comparable_games"]!,
      "visual_style": brief["visual_identity"]!,
      "target_audience": brief["target_audience"]!,
      "suitable_creator_types": brief["suitable_creator_types"]!,
      "content_hooks": brief["content_hooks"]!, "promotion_risks": brief["promotion_risks"]!,
    ]
    return GameProfile(
      id: id, name: name, steamAppID: appID, canonicalURL: url, favorite: favorite,
      currentFacts: facts, brief: brief, sourceStatus: ["status": .string("fresh")],
      lastAnalyzedAt: date(dayOffset: -3), nextAnalysisAt: date(dayOffset: 11),
      analysis: analysis, modelMetadata: ["model": .string("demo-fixture")],
      promptMetadata: ["language": .string("English")])
  }

  static func creator(
    id: UUID, name: String, channelID: String, url: String, favorite: Bool,
    subscribers: Int, focus: [String], performance: String,
    additionalContacts: [CreatorContact] = []
  ) -> CreatorProfile {
    let facts: JSONObject = [
      "description": .string(
        "Independent creator covering games with practical, honest commentary."),
      "country": .string("United States"),
      "published_at": .string("2019-04-18"),
      "subscriber_count": .integer(subscribers),
      "total_view_count": .integer(subscribers * 85),
      "public_video_count": .integer(420),
      "recent_metrics": .object([
        "recent_public_video_count": .integer(12),
        "numeric_view_sample_count": .integer(12),
        "average_views": .integer(max(12_000, subscribers / 3)),
        "median_views": .integer(max(10_000, subscribers / 4)),
        "publishing_frequency": .object([
          "uploads_per_30_days": .number(4.2), "sample_count": .integer(12),
          "span_days": .integer(86),
        ]),
      ]),
      "representative_videos": .array([
        .object([
          "title": .string("The indie game I could not stop playing"),
          "published_at": .string("2026-08-20"), "view_count": .integer(58_400),
          "duration_seconds": .integer(1_042),
        ])
      ]),
    ]
    let brief: JSONObject = [
      "positioning": .string("Trusted specialist with a high-intent PC gaming audience."),
      "content_focus": .object(["values": .array(focus.map(JSONValue.string))]),
      "formats": .array([.string("Edited reviews"), .string("First impressions")]),
      "style_and_pacing": .string("Analytical, warm, and concise."),
      "audience": .string("English-speaking PC and indie players aged 18–34."),
      "performance_context": .object(["value": .string(performance)]),
      "promotion_fit": .string(
        "Best for authentic hands-on coverage with room for editorial freedom."),
      "brand_safety": .string("Low observed risk in the reviewed public catalog."),
      "suitable_game_types": .array(focus.map(JSONValue.string)),
      "collaboration_risks": .array([.string("Requires enough lead time for hands-on play")]),
    ]
    let analysis: JSONObject = [
      "content_summary": .string("Creator focuses on \(focus.joined(separator: ", "))."),
      "recent_performance_summary": .string(performance),
      "engagement_summary": .string("Comments show strong purchase-intent discussion."),
      "publishing_frequency_context": .string("Usually publishes weekly."),
      "primary_games": .array(focus.map(JSONValue.string)),
      "genres": .array(focus.map(JSONValue.string)),
      "formats": brief["formats"]!, "style": .string("Editorial and evidence-led"),
      "pacing": .string("Measured"), "production_quality": .string("High"),
      "livestream_tendency": .string("Occasional"),
      "long_form_tendency": .string("Frequent"), "short_form_tendency": .string("Limited"),
      "representative_video_context": .string("Recent coverage matches the stated channel focus."),
      "sponsorship_patterns": .string("Clearly discloses sponsored integrations."),
      "brand_safety": brief["brand_safety"]!,
      "suitable_game_types": brief["suitable_game_types"]!,
      "collaboration_risks": brief["collaboration_risks"]!,
      "audience_inference": .object([
        "primary_language": .object([
          "value": .string("English"), "basis": .string("Public videos and channel copy"),
        ]),
        "likely_regions": .object([
          "values": .array([.string("North America"), .string("Europe")]),
          "basis": .string("Upload timing and public comments"),
        ]),
        "interests": .object([
          "values": .array(focus.map(JSONValue.string)),
          "basis": .string("Recent public catalog"),
        ]),
      ]),
    ]
    let primaryContact = CreatorContact(
      email: "\(slug(name))@example.test", availability: .discovered,
      source: "channel_about", sourceURL: url, validationState: "demo",
      purpose: "Partnerships")
    return CreatorProfile(
      id: id, name: name, youtubeChannelID: channelID, canonicalURL: url,
      favorite: favorite, currentFacts: facts, brief: brief,
      sourceStatus: ["status": .string("fresh")],
      lastAnalyzedAt: date(dayOffset: -2), nextAnalysisAt: date(dayOffset: 5),
      contact: primaryContact,
      manualNotes: nil, analysis: analysis,
      modelMetadata: ["model": .string("demo-fixture")],
      promptMetadata: ["language": .string("English")],
      contacts: [primaryContact] + additionalContacts)
  }

  static func match(
    id: UUID, game: GameProfile, creators: [CreatorProfile], dayOffset: Int
  ) -> MatchResult {
    let candidates = creators.enumerated().map { index, creator in
      candidate(
        creator, group: index < 3 ? .recommended : .other,
        label: index == 0 ? .strong : (index < 3 ? .good : .limited))
    }
    let created = date(dayOffset: dayOffset)
    return MatchResult(
      id: id, game: header(game), status: .succeeded, stage: .ranking,
      completedUnits: creators.count, totalUnits: creators.count,
      resultCount: creators.count, retryable: false, failure: nil,
      correlationID: "LOCAL-DEMO", supersedesID: nil,
      createdAt: created, updatedAt: created, startedAt: created, completedAt: created,
      state: .available,
      recommendedMatches: candidates.filter { $0.group == .recommended },
      otherMatches: candidates.filter { $0.group == .other })
  }

  static func refreshingCreators(
    in result: MatchResult,
    from profiles: [CreatorProfile]
  ) -> MatchResult {
    let profilesByID = Dictionary(uniqueKeysWithValues: profiles.map { ($0.id, $0) })
    func refresh(_ value: MatchCandidate) -> MatchCandidate {
      guard let profile = profilesByID[value.id] else { return value }
      let refreshedCreator = candidate(
        profile, group: value.group, label: value.label
      ).creator
      return MatchCandidate(
        creator: refreshedCreator,
        group: value.group,
        label: value.label,
        dimensionOutcomes: value.dimensionOutcomes,
        reasons: value.reasons,
        brief: value.brief,
        outreach: value.outreach)
    }

    return MatchResult(
      id: result.id,
      game: result.game,
      status: result.status,
      stage: result.stage,
      completedUnits: result.completedUnits,
      totalUnits: result.totalUnits,
      resultCount: result.resultCount,
      retryable: result.retryable,
      failure: result.failure,
      correlationID: result.correlationID,
      supersedesID: result.supersedesID,
      createdAt: result.createdAt,
      updatedAt: result.updatedAt,
      startedAt: result.startedAt,
      completedAt: result.completedAt,
      state: result.state,
      recommendedMatches: result.recommendedMatches.map(refresh),
      otherMatches: result.otherMatches.map(refresh))
  }

  static func recordingDeliveries(_ deliveries: [Delivery], in result: MatchResult) -> MatchResult {
    let deliveriesByCreator = Dictionary(
      uniqueKeysWithValues: deliveries.map { ($0.creatorID, $0) })
    func refresh(_ candidate: MatchCandidate) -> MatchCandidate {
      guard let delivery = deliveriesByCreator[candidate.id] else { return candidate }
      return MatchCandidate(
        creator: candidate.creator, group: candidate.group, label: candidate.label,
        dimensionOutcomes: candidate.dimensionOutcomes, reasons: candidate.reasons,
        brief: candidate.brief,
        outreach: MatchOutreach(
          deliveryID: delivery.id, sendState: delivery.sendState,
          responseState: delivery.responseState))
    }
    return MatchResult(
      id: result.id, game: result.game, status: result.status, stage: result.stage,
      completedUnits: result.completedUnits, totalUnits: result.totalUnits,
      resultCount: result.resultCount, retryable: result.retryable, failure: result.failure,
      correlationID: result.correlationID, supersedesID: result.supersedesID,
      createdAt: result.createdAt, updatedAt: result.updatedAt.addingTimeInterval(1),
      startedAt: result.startedAt, completedAt: result.completedAt, state: result.state,
      recommendedMatches: result.recommendedMatches.map(refresh),
      otherMatches: result.otherMatches.map(refresh))
  }

  static func candidate(
    _ creator: CreatorProfile, group: MatchGroup, label: MatchLabel
  ) -> MatchCandidate {
    let subscribers: Int?
    if case .integer(let value) = creator.currentFacts["subscriber_count"] {
      subscribers = value
    } else {
      subscribers = nil
    }
    return MatchCandidate(
      creator: MatchCreatorCard(
        id: creator.id, name: creator.name, youtubeChannelID: creator.youtubeChannelID,
        canonicalURL: creator.canonicalURL, favorite: creator.favorite,
        contactAvailable: !creator.contacts.isEmpty,
        contact: creator.contact.map {
          MatchCreatorContact(
            email: $0.email, source: $0.source, sourceURL: $0.sourceURL,
            validationState: $0.validationState, purpose: $0.purpose)
        },
        avatarURL: nil, performanceSummary: text(creator.brief["performance_context"]),
        subscriberCount: subscribers, recentAverageViews: subscribers.map { $0 / 3 },
        recentMedianViews: subscribers.map { $0 / 4 },
        contacts: creator.contacts.map {
          MatchCreatorContact(
            email: $0.email, source: $0.source, sourceURL: $0.sourceURL,
            validationState: $0.validationState, purpose: $0.purpose)
        }),
      group: group, label: label,
      dimensionOutcomes: MatchDimensionOutcomes(
        contentFit: label == .limited ? "Partial" : "Strong",
        audienceFit: label == .strong ? "Strong" : "Good",
        performanceFit: "Good", promotionFit: "Good", brandSafety: "Low risk"),
      reasons: [
        "Recent content overlaps with the Game Brief.",
        "Audience behavior suggests strong discovery potential.",
      ],
      brief: MatchBrief(
        contentFit: dimension("Channel topics align with the game's core loop."),
        audienceFit: dimension("The audience regularly engages with comparable releases."),
        performanceFit: dimension("Recent videos show dependable organic reach."),
        promotionFit: dimension("The creator's format supports an authentic first look."),
        brandSafety: dimension("No material concerns in the reviewed public sample."),
        strengths: ["Clear genre overlap", "Credible editorial voice"],
        risks: label == .limited ? ["Only partial genre overlap"] : [],
        evidence: ["Recent public videos", "Channel positioning", "View distribution"],
        matchReasons: ["Audience fit", "Content fit", "Reliable performance"]),
      outreach: MatchOutreach(deliveryID: nil, sendState: .notSent, responseState: .pending))
  }

  static func campaignFixture(
    match: MatchResult, creators: [CreatorProfile], template: OutreachTemplate
  ) -> OutreachCampaign {
    let campaignID = id(401)
    let batchID = id(402)
    let states: [ResponseState] = [.accepted, .declined, .noResponse]
    let deliveries = zip(creators.prefix(3), states).enumerated().map { index, pair in
      let (creator, response) = pair
      let sentAt = date(dayOffset: -1)
      return Delivery(
        id: id(410 + index), campaignID: campaignID, sendBatchID: batchID,
        creatorID: creator.id, creator: outreachCreator(creator),
        recipientEmail: creator.contact!.email, sendState: .sent, responseState: response,
        resendsDeliveryID: nil, supersededByDeliveryID: nil, isCurrent: true,
        templateName: template.name, templateVersion: template.version,
        renderedSubject: render(
          template.subjectTemplate, creator: creator.name, game: match.game.name),
        renderedMarkdown: render(
          template.bodyMarkdown, creator: creator.name, game: match.game.name),
        renderedHTML: "<p>Demo outreach preview</p>", senderName: "Find Me Gamer Team",
        senderAddress: "outreach@example.test", replyTo: "outreach@example.test",
        acceptedLabel: template.acceptedLabel, declinedLabel: template.declinedLabel,
        smtpFailure: nil, canResend: false, createdAt: sentAt,
        sendingAt: sentAt, sentAt: sentAt, failedAt: nil,
        respondedAt: response == .noResponse ? nil : date(dayOffset: 0), supersededAt: nil)
    }
    let batch = SendBatch(
      id: batchID, campaignID: campaignID, matchTaskID: match.id,
      templateID: template.id, templateName: template.name, templateVersion: template.version,
      requestedCreatorIDs: deliveries.map(\.creatorID), requestedAt: date(dayOffset: -1),
      state: .sent, deliveries: deliveries)
    return OutreachCampaign(
      id: campaignID, matchTaskID: match.id, game: campaignGame(match.game),
      state: .completed, sendBatchCount: 1,
      metrics: CampaignMetrics(
        sentCreators: 3, accepted: 1, declined: 1, noResponse: 1,
        failed: 0, responseRate: 2.0 / 3.0),
      createdAt: date(dayOffset: -2), latestActivityAt: date(dayOffset: 0),
      sendBatches: [batch])
  }

  static func card(_ profile: GameProfile) -> GameProfileCard {
    GameProfileCard(
      id: profile.id, name: profile.name, steamAppID: profile.steamAppID,
      canonicalURL: profile.canonicalURL, favorite: profile.favorite,
      currentFacts: profile.currentFacts, brief: profile.brief,
      sourceStatus: profile.sourceStatus, lastAnalyzedAt: profile.lastAnalyzedAt,
      nextAnalysisAt: profile.nextAnalysisAt)
  }

  static func card(_ profile: CreatorProfile) -> CreatorProfileCard {
    CreatorProfileCard(
      id: profile.id, name: profile.name, youtubeChannelID: profile.youtubeChannelID,
      canonicalURL: profile.canonicalURL, favorite: profile.favorite,
      currentFacts: profile.currentFacts, brief: profile.brief,
      sourceStatus: profile.sourceStatus, lastAnalyzedAt: profile.lastAnalyzedAt,
      nextAnalysisAt: profile.nextAnalysisAt, contact: profile.contact,
      contacts: profile.contacts)
  }

  static func replacingFavorite(_ profile: GameProfile, favorite: Bool) -> GameProfile {
    GameProfile(
      id: profile.id, name: profile.name, steamAppID: profile.steamAppID,
      canonicalURL: profile.canonicalURL, favorite: favorite,
      currentFacts: profile.currentFacts, brief: profile.brief,
      sourceStatus: profile.sourceStatus, lastAnalyzedAt: profile.lastAnalyzedAt,
      nextAnalysisAt: profile.nextAnalysisAt, analysis: profile.analysis,
      modelMetadata: profile.modelMetadata, promptMetadata: profile.promptMetadata)
  }

  static func replacingFavorite(_ profile: CreatorProfile, favorite: Bool) -> CreatorProfile {
    CreatorProfile(
      id: profile.id, name: profile.name, youtubeChannelID: profile.youtubeChannelID,
      canonicalURL: profile.canonicalURL, favorite: favorite,
      currentFacts: profile.currentFacts, brief: profile.brief,
      sourceStatus: profile.sourceStatus, lastAnalyzedAt: profile.lastAnalyzedAt,
      nextAnalysisAt: profile.nextAnalysisAt, contact: profile.contact,
      manualNotes: profile.manualNotes, analysis: profile.analysis,
      modelMetadata: profile.modelMetadata, promptMetadata: profile.promptMetadata,
      contacts: profile.contacts)
  }

  static func replacingDefault(_ template: OutreachTemplate, isDefault: Bool)
    -> OutreachTemplate
  {
    OutreachTemplate(
      id: template.id, name: template.name, version: template.version,
      subjectTemplate: template.subjectTemplate, bodyMarkdown: template.bodyMarkdown,
      acceptedLabel: template.acceptedLabel, declinedLabel: template.declinedLabel,
      isDefault: isDefault, createdAt: template.createdAt, updatedAt: template.updatedAt)
  }

  static func task(_ result: MatchResult) -> MatchTask {
    MatchTask(
      id: result.id, game: result.game, status: result.status, stage: result.stage,
      completedUnits: result.completedUnits, totalUnits: result.totalUnits,
      resultCount: result.resultCount, retryable: result.retryable,
      failure: result.failure, correlationID: result.correlationID,
      supersedesID: result.supersedesID, createdAt: result.createdAt,
      updatedAt: result.updatedAt, startedAt: result.startedAt,
      completedAt: result.completedAt)
  }

  static func summary(_ campaign: OutreachCampaign) -> CampaignSummary {
    CampaignSummary(
      id: campaign.id, matchTaskID: campaign.matchTaskID, game: campaign.game,
      state: campaign.state, sendBatchCount: campaign.sendBatchCount,
      metrics: campaign.metrics, createdAt: campaign.createdAt,
      latestActivityAt: campaign.latestActivityAt)
  }

  static func header(_ game: GameProfile) -> MatchGameHeader {
    MatchGameHeader(
      id: game.id, name: game.name, steamAppID: game.steamAppID,
      canonicalURL: game.canonicalURL, coverURL: nil)
  }

  static func campaignGame(_ game: MatchGameHeader) -> CampaignGame {
    CampaignGame(
      id: game.id, name: game.name, steamAppID: game.steamAppID,
      steamURL: game.canonicalURL, coverURL: game.coverURL)
  }

  static func outreachCreator(_ creator: CreatorProfile) -> OutreachCreator {
    OutreachCreator(
      id: creator.id, name: creator.name, youtubeChannelID: creator.youtubeChannelID,
      canonicalURL: creator.canonicalURL, avatarURL: nil)
  }

  static func dimension(_ analysis: String) -> MatchBriefDimension {
    MatchBriefDimension(analysis: analysis, evidence: ["Local demo fixture"])
  }

  static func render(_ source: String, creator: String, game: String) -> String {
    source
      .replacingOccurrences(of: "{{creator_name}}", with: creator)
      .replacingOccurrences(of: "{{channel_name}}", with: creator)
      .replacingOccurrences(of: "{{game_name}}", with: game)
      .replacingOccurrences(of: "{{steam_url}}", with: "https://store.steampowered.com")
      .replacingOccurrences(of: "{{game_summary}}", with: "A promising indie game.")
      .replacingOccurrences(of: "{{match_reason}}", with: "Strong audience overlap.")
      .replacingOccurrences(of: "{{sender_name}}", with: "Find Me Gamer Team")
  }

  static func text(_ value: JSONValue?) -> String? {
    switch value {
    case .string(let text): return text
    case .object(let object): return text(object["value"])
    default: return nil
    }
  }

  static func id(_ suffix: Int) -> UUID {
    UUID(uuidString: String(format: "DE000000-0000-4000-8000-%012d", suffix))!
  }

  static func date(dayOffset: Int) -> Date {
    Date(timeIntervalSince1970: 1_788_134_400 + Double(dayOffset * 86_400))
  }

  static func slug(_ value: String) -> String {
    value.lowercased().replacingOccurrences(of: " ", with: ".")
  }
}

actor DemoWorkspaceKeyStore: WorkspaceKeyStore {
  func read() async throws -> String? { "local-demo-workspace" }
  func save(_ key: String) async throws {}
  func delete() async throws {}
}

final class DemoConnectivityMonitor: ConnectivityMonitoring, @unchecked Sendable {
  func start(handler: @escaping @Sendable (Bool) -> Void) {}
  func cancel() {}
}
