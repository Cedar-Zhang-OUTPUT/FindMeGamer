import FindMeGamerAPI
import Foundation
import OpenAPIRuntime
import OpenAPIURLSession

public struct OpenAPIService: APIService, Sendable {
  private let client: Client

  public init(
    baseURL: URL,
    keyProvider: @escaping @Sendable () async throws -> String?
  ) {
    self.init(
      baseURL: baseURL, transport: URLSessionTransport(), keyProvider: keyProvider,
      correlationIDProvider: { UUID().uuidString })
  }

  init(
    baseURL: URL, transport: any ClientTransport,
    keyProvider: @escaping WorkspaceAuthMiddleware.KeyProvider,
    correlationIDProvider: @escaping WorkspaceAuthMiddleware.CorrelationIDProvider
  ) {
    client = Client(
      serverURL: baseURL,
      configuration: .init(dateTranscoder: RFC3339DateTranscoder()),
      transport: transport,
      middlewares: [
        WorkspaceAuthMiddleware(
          keyProvider: keyProvider, correlationIDProvider: correlationIDProvider)
      ])
  }

  public func validateSession() async throws -> WorkspaceSession {
    let value = try await perform { try await client.validateSession() }.ok.body.json
    return WorkspaceSession(
      workspaceName: value.workspace_name, apiVersion: value.api_version,
      serviceConnections: value.service_connections.additionalProperties)
  }

  public func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage {
    let queryStatus = status.flatMap {
      Operations.listJobs.Input.Query.statusPayload(rawValue: $0.rawValue)
    }
    let value = try await perform {
      try await client.listJobs(
        .init(query: .init(changed_after: changedAfter, status: queryStatus)))
    }.ok.body.json
    return try DomainMapper.jobChangePage(value)
  }

  public func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  {
    let generated = Components.Schemas.AnalysisJobCreate(
      mode: request.mode.flatMap { Components.Schemas.JobMode(rawValue: $0.rawValue) },
      target_type: Components.Schemas.TargetType(rawValue: request.profileType.rawValue)!,
      url: request.url)
    let output = try await perform {
      try await client.createAnalysisJob(
        .init(
          headers: .init(Idempotency_hyphen_Key: idempotencyKey), body: .json(generated)))
    }
    switch output {
    case .ok(let response): return try mapSubmission(response.body.json)
    case .created(let response): return try mapSubmission(response.body.json)
    default: throw APIError.invalidResponse
    }
  }

  public func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    let output = try await perform {
      try await client.retryAnalysisJob(
        .init(
          path: .init(job_id: id.uuidString),
          headers: .init(Idempotency_hyphen_Key: idempotencyKey),
          body: .json(.init())))
    }
    switch output {
    case .ok(let response): return try DomainMapper.analysisJob(response.body.json)
    case .created(let response): return try DomainMapper.analysisJob(response.body.json)
    default: throw APIError.invalidResponse
    }
  }

  public func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    switch type {
    case .game:
      let value = try await perform {
        try await client.listGameProfiles(
          .init(
            query: .init(
              query: query, only_collection: onlyCollection, cursor: cursor, limit: limit)))
      }.ok.body.json
      return ProfileCardPage(
        items: try value.items.map { .game(try DomainMapper.gameCard($0)) },
        nextCursor: value.next_cursor)
    case .creator:
      let value = try await perform {
        try await client.listCreatorProfiles(
          .init(
            query: .init(
              query: query, only_collection: onlyCollection, cursor: cursor, limit: limit)))
      }.ok.body.json
      return ProfileCardPage(
        items: try value.items.map { .creator(try DomainMapper.creatorCard($0)) },
        nextCursor: value.next_cursor)
    }
  }

  public func profile(type: ProfileType, id: UUID) async throws -> Profile {
    let value = try await perform {
      try await client.getProfile(
        .init(path: .init(profile_id: id.uuidString, profile_type: type.profileRouteComponent)))
    }.ok.body.json
    switch (type, value.value1, value.value2) {
    case (.game, let game?, nil): return .game(try DomainMapper.gameProfile(game))
    case (.creator, nil, let creator?): return .creator(try DomainMapper.creatorProfile(creator))
    default: throw APIError.invalidResponse
    }
  }

  public func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws
    -> ProfileCard
  {
    let value = try await perform {
      try await client.setProfileFavorite(
        .init(
          path: .init(profile_id: id.uuidString, profile_type: type.profileRouteComponent),
          body: .json(.init(favorite: favorite))))
    }.ok.body.json
    switch (type, value.value1, value.value2) {
    case (.game, let game?, nil): return .game(try DomainMapper.gameCard(game))
    case (.creator, nil, let creator?): return .creator(try DomainMapper.creatorCard(creator))
    default: throw APIError.invalidResponse
    }
  }

  public func profileEdit(type: ProfileType, id: UUID) async throws -> ProfileEditDocument {
    let value = try await perform {
      try await client.getProfileEdit(.init(path: .init(profile_type: type.rawValue, profile_id: id.uuidString)))
    }.ok.body.json
    return try DomainMapper.profileEdit(value)
  }

  public func saveProfileEdit(type: ProfileType, id: UUID, patch: ProfileEditPatch) async throws -> ProfileEditDocument {
    let generated = Components.Schemas.ProfileEditPatch(
      changes: .init(additionalProperties: patch.changes.mapValues { value in
        switch value {
        case .text(let text): .init(value1: text)
        case .list(let items): .init(value2: items)
        }
      }), expected_revision: patch.expectedRevision, reset_fields: patch.resetFields)
    let value = try await perform {
      try await client.updateProfileEdit(.init(
        path: .init(profile_type: type.rawValue, profile_id: id.uuidString), body: .json(generated)))
    }.ok.body.json
    return try DomainMapper.profileEdit(value)
  }

  public func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  {
    let value = try await perform {
      try await client.updateCreatorManual(
        .init(
          path: .init(profile_id: id.uuidString),
          body: .json(.init(contact_email: email, notes: notes))))
    }.ok.body.json
    return try DomainMapper.creatorProfile(value)
  }

  public func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    let value = try await perform {
      try await client.createMatch(
        .init(
          headers: .init(Idempotency_hyphen_Key: idempotencyKey),
          body: .json(.init(game_id: gameID.uuidString))))
    }.accepted.body.json
    return try DomainMapper.matchTask(value)
  }

  public func listMatches(cursor: String?) async throws -> MatchTaskPage {
    let value = try await perform {
      try await client.listMatches(.init(query: .init(cursor: cursor)))
    }.ok.body.json
    return MatchTaskPage(
      items: try value.items.map(DomainMapper.matchTask), cursor: value.cursor,
      hasMore: value.has_more)
  }

  public func match(id: UUID) async throws -> MatchResult {
    let value = try await perform {
      try await client.getMatch(.init(path: .init(match_task_id: id.uuidString)))
    }.ok.body.json
    return try DomainMapper.matchResult(value)
  }

  public func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    let value = try await perform {
      try await client.retryMatch(
        .init(
          path: .init(match_task_id: id.uuidString),
          headers: .init(Idempotency_hyphen_Key: idempotencyKey)))
    }.accepted.body.json
    return try DomainMapper.matchTask(value)
  }

  public func listCampaigns(cursor: String?) async throws -> CampaignPage {
    let value = try await perform {
      try await client.listOutreachCampaigns(.init(query: .init(cursor: cursor)))
    }.ok.body.json
    return CampaignPage(
      items: try value.items.map(DomainMapper.campaignSummary), cursor: value.cursor,
      hasMore: value.has_more)
  }

  public func campaign(id: UUID) async throws -> OutreachCampaign {
    let value = try await perform {
      try await client.getOutreachCampaign(.init(path: .init(campaign_id: id.uuidString)))
    }.ok.body.json
    return try DomainMapper.campaign(value)
  }

  public func listTemplates() async throws -> [OutreachTemplate] {
    try await perform { try await client.listOutreachTemplates() }.ok.body.json.items.map(
      DomainMapper.template)
  }

  public func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    if let id = draft.id {
      let value = try await perform {
        try await client.updateOutreachTemplate(
          .init(
            path: .init(template_id: id.uuidString),
            body: .json(
              .init(
                accepted_label: draft.acceptedLabel, body_markdown: draft.bodyMarkdown,
                declined_label: draft.declinedLabel, name: draft.name,
                subject_template: draft.subjectTemplate))))
      }.ok.body.json
      return try DomainMapper.template(value)
    }
    let value = try await perform {
      try await client.createOutreachTemplate(
        .init(
          body: .json(
            .init(
              accepted_label: draft.acceptedLabel, body_markdown: draft.bodyMarkdown,
              declined_label: draft.declinedLabel, name: draft.name,
              subject_template: draft.subjectTemplate))))
    }.created.body.json
    return try DomainMapper.template(value)
  }

  public func duplicateTemplate(id: UUID) async throws -> OutreachTemplate {
    let value = try await perform {
      try await client.duplicateOutreachTemplate(.init(path: .init(template_id: id.uuidString)))
    }.created.body.json
    return try DomainMapper.template(value)
  }

  public func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate {
    let value = try await perform {
      try await client.setDefaultOutreachTemplate(.init(path: .init(template_id: id.uuidString)))
    }.ok.body.json
    return try DomainMapper.template(value)
  }

  public func deleteTemplate(id: UUID) async throws {
    _ = try await perform {
      try await client.deleteOutreachTemplate(.init(path: .init(template_id: id.uuidString)))
    }.noContent
  }

  public func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    guard let id = draft.id else {
      throw APIError(
        code: "template_not_saved", message: "Save the template before previewing it.",
        retryable: false)
    }
    let value = try await perform {
      try await client.previewOutreachTemplate(
        .init(
          path: .init(template_id: id.uuidString),
          body: .json(
            .init(
              value1: .init(
                accepted_label: draft.acceptedLabel, body_markdown: draft.bodyMarkdown,
                declined_label: draft.declinedLabel,
                subject_template: draft.subjectTemplate)))))
    }.ok.body.json
    return DomainMapper.renderedEmail(value)
  }

  public func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    let value = try await perform {
      try await client.previewOutreachSendBatch(.init(body: .json(sendBatchRequest(request))))
    }.ok.body.json
    return try value.items.map(DomainMapper.recipientPreview)
  }

  public func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  {
    let value = try await perform {
      try await client.createOutreachSendBatch(
        .init(
          headers: .init(Idempotency_hyphen_Key: idempotencyKey),
          body: .json(sendBatchRequest(request))))
    }.created.body.json
    return try DomainMapper.sendBatchResponse(value)
  }

  public func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    let value = try await perform {
      try await client.resendOutreachDelivery(
        .init(
          path: .init(delivery_id: id.uuidString),
          headers: .init(Idempotency_hyphen_Key: idempotencyKey)))
    }.created.body.json
    guard let delivery = value.deliveries.first else { throw APIError.invalidResponse }
    return try DomainMapper.deliverySummary(
      delivery, campaignID: value.campaign_id, sendBatchID: value.id)
  }

  public func smtpSettings() async throws -> SMTPSettingsStatus {
    try DomainMapper.smtpSettings(
      try await perform { try await client.getOutreachSMTPSettings() }.ok.body.json)
  }

  public func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    let encryption = draft.encryption.flatMap {
      Components.Schemas.SMTPSettingsUpdate.encryptionPayload(
        rawValue: $0 == .startTLS ? "starttls" : $0.rawValue)
    }
    let value = try await perform {
      try await client.updateOutreachSMTPSettings(
        .init(
          body: .json(
            .init(
              emails_per_minute: draft.emailsPerMinute, encryption: encryption,
              from_name: draft.fromName, host: draft.host, password: draft.password,
              port: draft.port, reply_to: draft.replyTo, username: draft.username))))
    }.ok.body.json
    return try DomainMapper.smtpSettings(value)
  }

  public func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws
    -> ConnectionTestResult
  {
    guard draft == nil else {
      throw APIError(
        code: "smtp_draft_test_unsupported",
        message: "Save the email settings before testing the connection.", retryable: false)
    }
    return DomainMapper.testResult(
      try await perform { try await client.testOutreachSMTPConnection() }.ok.body.json)
  }

  public func sendSMTPTest(to email: String) async throws -> ConnectionTestResult {
    DomainMapper.testResult(
      try await perform {
        try await client.sendOutreachSMTPTestEmail(
          .init(body: .json(.init(recipient: email))))
      }.ok.body.json)
  }

  public func sharedSettings() async throws -> SharedSettings {
    DomainMapper.sharedSettings(
      try await perform { try await client.getReanalysisSettings() }.ok.body.json)
  }

  public func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    DomainMapper.sharedSettings(
      try await perform {
        try await client.updateReanalysisSettings(
          .init(
            body: .json(
              .init(
                creator_interval_days: draft.creatorIntervalDays,
                game_interval_days: draft.gameIntervalDays))))
      }.ok.body.json)
  }

  public func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    DomainMapper.connectionStatus(
      try await perform {
        try await client.getConnectionStatus(.init(path: .init(service: service.rawValue)))
      }.ok.body.json,
      service: service)
  }

  public func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  {
    DomainMapper.connectionStatus(
      try await perform {
        try await client.replaceConnectionSecret(
          .init(
            path: .init(service: service.rawValue),
            body: .json(.init(secret: secret))))
      }.ok.body.json,
      service: service)
  }

  public func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult {
    let value = try await perform {
      try await client.testConnection(.init(path: .init(service: service.rawValue)))
    }.ok.body.json
    return DomainMapper.connectionTestResult(value)
  }

  private func perform<Value: Sendable>(
    _ operation: @Sendable () async throws -> Value
  ) async throws -> Value {
    do {
      return try await operation()
    } catch let clientError as ClientError {
      if let apiError = clientError.underlyingError as? APIError { throw apiError }
      if clientError.underlyingError is DecodingError { throw APIError.invalidResponse }
      throw clientError.underlyingError
    }
  }

  private func sendBatchRequest(_ request: SendBatchDraft)
    -> Components.Schemas.OutreachSendBatchRequest
  {
    let recipientSelections = request.recipientSelections.map {
      Components.Schemas.OutreachRecipientSelection(
        creator_id: $0.creatorID.uuidString,
        email: $0.email)
    }
    return .init(
      body_markdown_override: request.bodyMarkdownOverride,
      creator_ids: request.creatorIDs.map(\.uuidString),
      match_task_id: request.matchTaskID.uuidString,
      recipient_selections: recipientSelections.isEmpty ? nil : recipientSelections,
      subject_override: request.subjectOverride, template_id: request.templateID?.uuidString)
  }

  private func mapSubmission(
    _ value: Operations.createAnalysisJob.Output.Ok.Body.jsonPayload
  ) throws -> AnalysisSubmission {
    switch value {
    case .existing_profile(let profile): .existingProfile(try DomainMapper.existingProfile(profile))
    case .job(let job): .job(try DomainMapper.analysisJob(job))
    }
  }

  private func mapSubmission(
    _ value: Operations.createAnalysisJob.Output.Created.Body.jsonPayload
  ) throws -> AnalysisSubmission {
    switch value {
    case .existing_profile(let profile): .existingProfile(try DomainMapper.existingProfile(profile))
    case .job(let job): .job(try DomainMapper.analysisJob(job))
    }
  }
}

extension ProfileType {
  fileprivate var profileRouteComponent: String {
    switch self {
    case .game: "games"
    case .creator: "creators"
    }
  }
}

struct RFC3339DateTranscoder: DateTranscoder {
  private let standard = ISO8601DateTranscoder()
  private let fractional = ISO8601DateTranscoder(
    options: [.withInternetDateTime, .withFractionalSeconds])

  func encode(_ date: Date) throws -> String {
    try standard.encode(date)
  }

  func decode(_ dateString: String) throws -> Date {
    do {
      return try fractional.decode(dateString)
    } catch {
      return try standard.decode(dateString)
    }
  }
}
