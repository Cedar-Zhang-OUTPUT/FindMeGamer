import FindMeGamerAPI
import Foundation
import OpenAPIRuntime

enum DomainMapper {
  static func profileEdit(_ value: Components.Schemas.ProfileEditDocument) throws
    -> ProfileEditDocument
  {
    func editValue(_ value: Components.Schemas.EditValue) throws -> ProfileEditValue {
      switch (value.value1, value.value2) {
      case (let text?, nil): .text(text)
      case (nil, let items?): .list(items)
      default: throw APIError.invalidResponse
      }
    }
    return ProfileEditDocument(
      profileType: value.profile_type == .game ? .game : .creator,
      profileID: try uuid(value.profile_id), revision: value.revision,
      fields: try value.fields.map {
        .init(
          key: $0.key, section: $0.section.rawValue, label: $0.label, kind: $0.kind.rawValue,
          required: $0.required, value: try editValue($0.value),
          sourceValue: try $0.source_value.map { try editValue($0.value1) },
          isOverridden: $0.is_overridden)
      })
  }
  static func gameCard(_ value: Components.Schemas.GameProfileCard) throws -> GameProfileCard {
    var result = GameProfileCard(
      id: try uuid(value.id), name: value.name, steamAppID: value.steam_app_id,
      canonicalURL: value.canonical_url, favorite: value.favorite,
      currentFacts: try json(value.current_facts), brief: try json(value.brief),
      sourceStatus: try json(value.source_status), lastAnalyzedAt: value.last_analyzed_at,
      nextAnalysisAt: value.next_analysis_at)
    result.profileRevision = value.profile_revision ?? 0
    result.manualOverrides = try overrides(value.manual_overrides?.additionalProperties)
    return result
  }

  static func creatorCard(_ value: Components.Schemas.CreatorProfileCard) throws
    -> CreatorProfileCard
  {
    let preferredContact = contact(value.contact?.value1)
    var result = CreatorProfileCard(
      id: try uuid(value.id), name: value.name, youtubeChannelID: value.youtube_channel_id,
      platformAccountID: value.platform_account_id,
      canonicalURL: value.canonical_url, favorite: value.favorite,
      currentFacts: try json(value.current_facts), brief: try json(value.brief),
      sourceStatus: try json(value.source_status), lastAnalyzedAt: value.last_analyzed_at,
      nextAnalysisAt: value.next_analysis_at, contact: preferredContact,
      contacts: contacts(value.contacts, fallback: preferredContact))
    result.platformAccountID = value.platform_account_id
    result.profileRevision = value.profile_revision ?? 0
    result.manualOverrides = try overrides(value.manual_overrides?.additionalProperties)
    return result
  }

  static func gameProfile(_ value: Components.Schemas.GameProfileDetail) throws -> GameProfile {
    var result = GameProfile(
      id: try uuid(value.id), name: value.name, steamAppID: value.steam_app_id,
      canonicalURL: value.canonical_url, favorite: value.favorite,
      currentFacts: try json(value.current_facts), brief: try json(value.brief),
      sourceStatus: try json(value.source_status), lastAnalyzedAt: value.last_analyzed_at,
      nextAnalysisAt: value.next_analysis_at, analysis: try json(value.analysis),
      modelMetadata: try json(value.model_metadata), promptMetadata: try json(value.prompt_metadata)
    )
    result.profileRevision = value.profile_revision ?? 0
    result.manualOverrides = try overrides(value.manual_overrides?.additionalProperties)
    return result
  }

  static func creatorProfile(_ value: Components.Schemas.CreatorProfileDetail) throws
    -> CreatorProfile
  {
    let preferredContact = contact(value.contact?.value1)
    var result = CreatorProfile(
      id: try uuid(value.id), name: value.name, youtubeChannelID: value.youtube_channel_id,
      platformAccountID: value.platform_account_id,
      canonicalURL: value.canonical_url, favorite: value.favorite,
      currentFacts: try json(value.current_facts), brief: try json(value.brief),
      sourceStatus: try json(value.source_status), lastAnalyzedAt: value.last_analyzed_at,
      nextAnalysisAt: value.next_analysis_at, contact: preferredContact,
      manualNotes: value.manual_notes, analysis: try json(value.analysis),
      modelMetadata: try json(value.model_metadata),
      promptMetadata: try json(value.prompt_metadata),
      contacts: contacts(value.contacts, fallback: preferredContact)
    )
    result.platformAccountID = value.platform_account_id
    result.profileRevision = value.profile_revision ?? 0
    result.manualOverrides = try overrides(value.manual_overrides?.additionalProperties)
    return result
  }

  private static func overrides(_ values: [String: Components.Schemas.EditValue]?) throws
    -> [String: ProfileEditValue]
  {
    try (values ?? [:]).mapValues {
      switch ($0.value1, $0.value2) {
      case (let text?, nil): .text(text)
      case (nil, let list?): .list(list)
      default: throw APIError.invalidResponse
      }
    }
  }

  static func analysisJob(_ value: Components.Schemas.AnalysisJobResponse) throws -> AnalysisJob {
    try analysisJob(
      id: value.id, profileType: value.target_type.rawValue,
      canonicalTargetID: value.canonical_target_id, canonicalURL: value.canonical_url,
      mode: value.mode.rawValue, status: value.status.rawValue, stage: value.stage?.value1.rawValue,
      completedUnits: value.completed_units, totalUnits: value.total_units,
      retryable: value.retryable, correlationID: value.correlation_id, profileID: value.profile_id,
      createdAt: value.created_at, updatedAt: value.updated_at, startedAt: value.started_at,
      completedAt: value.completed_at,
      failure: value.error.map {
        JobFailure(code: $0.value1.code, message: $0.value1.message.rawValue)
      })
  }

  static func existingProfile(_ value: Components.Schemas.ExistingProfileResponse) throws
    -> ExistingProfile
  {
    ExistingProfile(
      profileID: try uuid(value.existing_profile_id),
      profileType: try profileType(value.target_type.rawValue),
      canonicalTargetID: value.canonical_target_id, canonicalURL: value.canonical_url)
  }

  static func jobChangePage(_ value: Components.Schemas.ChangedJobsResponse) throws -> JobChangePage
  {
    JobChangePage(
      items: try value.items.map {
        switch $0 {
        case .analysis(let item):
          return .analysis(
            try analysisJob(
              id: item.id, profileType: item.target_type.rawValue,
              canonicalTargetID: item.canonical_target_id, canonicalURL: item.canonical_url,
              mode: item.mode.rawValue, status: item.status.rawValue,
              stage: item.stage?.value1.rawValue, completedUnits: item.completed_units,
              totalUnits: item.total_units, retryable: item.retryable,
              correlationID: item.correlation_id, profileID: item.profile_id,
              createdAt: item.created_at, updatedAt: item.updated_at, startedAt: item.started_at,
              completedAt: item.completed_at,
              failure: item.error.map {
                JobFailure(code: $0.value1.code, message: $0.value1.message.rawValue)
              }))
        case .match(let item):
          return .match(
            ChangedMatchJob(
              id: try uuid(item.resource_id), gameID: try uuid(item.game_id),
              status: try jobStatus(item.status.rawValue),
              stage: try matchStage(item.stage.rawValue),
              completedUnits: item.completed_units, totalUnits: item.total_units,
              resultCount: item.result_count, retryable: item.retryable,
              failure: item.error.map {
                JobFailure(code: $0.value1.code, message: $0.value1.message.rawValue)
              }, correlationID: item.correlation_id,
              supersedesID: try optionalUUID(item.supersedes_id),
              createdAt: item.created_at, updatedAt: item.updated_at,
              startedAt: item.started_at, completedAt: item.completed_at))
        }
      }, cursor: value.cursor, hasMore: value.has_more,
      affectedProfileIDs: try value.affected_profile_ids.map(uuid))
  }

  static func matchTask(_ value: Components.Schemas.MatchSummary) throws -> MatchTask {
    MatchTask(
      id: try uuid(value.id), game: try matchGame(value.game),
      status: try jobStatus(value.status.rawValue), stage: try matchStage(value.stage.rawValue),
      completedUnits: value.completed_units, totalUnits: value.total_units,
      resultCount: value.result_count, retryable: value.retryable,
      failure: value.error.map {
        JobFailure(code: $0.value1.code, message: $0.value1.message.rawValue)
      },
      correlationID: value.correlation_id, supersedesID: try optionalUUID(value.supersedes_id),
      createdAt: value.created_at, updatedAt: value.updated_at, startedAt: value.started_at,
      completedAt: value.completed_at)
  }

  static func matchResult(_ value: Components.Schemas.MatchDetail) throws -> MatchResult {
    var result = MatchResult(
      id: try uuid(value.id), game: try matchGame(value.game),
      status: try jobStatus(value.status.rawValue), stage: try matchStage(value.stage.rawValue),
      completedUnits: value.completed_units, totalUnits: value.total_units,
      resultCount: value.result_count, retryable: value.retryable,
      failure: value.error.map {
        JobFailure(code: $0.value1.code, message: $0.value1.message.rawValue)
      },
      correlationID: value.correlation_id, supersedesID: try optionalUUID(value.supersedes_id),
      createdAt: value.created_at, updatedAt: value.updated_at, startedAt: value.started_at,
      completedAt: value.completed_at, state: try resultState(value.result_state.rawValue),
      recommendedMatches: try value.recommended_matches.map(candidate),
      otherMatches: try value.other_matches.map(candidate))
    result.profileRevisions = try (value.profile_revisions ?? []).map {
      .init(
        profileType: $0.profile_type == .game ? .game : .creator,
        profileID: try uuid($0.profile_id), snapshotRevision: $0.snapshot_revision,
        currentRevision: $0.current_revision)
    }
    return result
  }

  static func campaign(_ value: Components.Schemas.OutreachCampaignDetail) throws
    -> OutreachCampaign
  {
    let matchTaskID = try uuid(value.match_task_id)
    return OutreachCampaign(
      id: try uuid(value.id), matchTaskID: matchTaskID,
      game: try campaignGame(value.game), state: try campaignState(value.state.rawValue),
      sendBatchCount: value.send_batch_count, metrics: campaignMetrics(value.metrics),
      createdAt: value.created_at, latestActivityAt: value.latest_activity_at,
      sendBatches: try value.send_batches.map { try sendBatch($0, matchTaskID: matchTaskID) })
  }

  static func campaignSummary(_ value: Components.Schemas.OutreachCampaignSummary) throws
    -> CampaignSummary
  {
    CampaignSummary(
      id: try uuid(value.id), matchTaskID: try uuid(value.match_task_id),
      game: try campaignGame(value.game), state: try campaignState(value.state.rawValue),
      sendBatchCount: value.send_batch_count, metrics: campaignMetrics(value.metrics),
      createdAt: value.created_at, latestActivityAt: value.latest_activity_at)
  }

  static func template(_ value: Components.Schemas.OutreachTemplateResponse) throws
    -> OutreachTemplate
  {
    OutreachTemplate(
      id: try uuid(value.id), name: value.name, version: value.version,
      subjectTemplate: value.subject_template, bodyMarkdown: value.body_markdown,
      acceptedLabel: value.accepted_label, declinedLabel: value.declined_label,
      isDefault: value.is_default, createdAt: value.created_at, updatedAt: value.updated_at)
  }

  static func renderedEmail(_ value: Components.Schemas.RenderedDelivery) -> RenderedEmail {
    RenderedEmail(subject: value.subject, markdown: value.markdown, html: value.html)
  }

  static func smtpSettings(_ value: Components.Schemas.SMTPSettingsResponse) throws
    -> SMTPSettingsStatus
  {
    SMTPSettingsStatus(
      configured: value.configured, host: value.host, port: value.port,
      encryption: try value.encryption.map { try smtpEncryption($0.rawValue) },
      username: value.username, fromName: value.from_name, replyTo: value.reply_to,
      emailsPerMinute: value.emails_per_minute,
      lastTestStatus: connectionTestStatus(value.last_test_status?.rawValue),
      lastTestedAt: value.last_tested_at)
  }

  static func connectionStatus(
    _ value: Components.Schemas.ConnectionStatusResponse, service: ConnectionService
  ) -> ConnectionStatus {
    ConnectionStatus(
      service: service, configured: value.configured,
      lastTestStatus: connectionTestStatus(value.last_test_status?.rawValue),
      lastTestedAt: value.last_tested_at)
  }

  static func sharedSettings(_ value: Components.Schemas.ReanalysisSettingsResponse)
    -> SharedSettings
  {
    SharedSettings(
      gameIntervalDays: value.game_interval_days,
      creatorIntervalDays: value.creator_interval_days)
  }

  static func testResult(_ value: Components.Schemas.SMTPTestResult) -> ConnectionTestResult {
    ConnectionTestResult(
      succeeded: value.succeeded,
      status: connectionTestStatus(value.last_test_status.rawValue), testedAt: value.last_tested_at)
  }

  static func connectionTestResult(_ value: Components.Schemas.ConnectionStatusResponse)
    -> ConnectionTestResult
  {
    let status = connectionTestStatus(value.last_test_status?.rawValue)
    return ConnectionTestResult(
      succeeded: status == .success, status: status, testedAt: value.last_tested_at)
  }

  static func recipientPreview(_ value: Components.Schemas.OutreachSendBatchPreviewItem) throws
    -> RecipientPreview
  {
    RecipientPreview(
      creatorID: try uuid(value.creator_id), creatorName: value.creator_name,
      recipientEmail: value.recipient_email, subject: value.subject,
      markdown: value.markdown, html: value.html)
  }

  static func sendBatchResponse(_ value: Components.Schemas.OutreachSendBatchResponse) throws
    -> SendBatch
  {
    SendBatch(
      id: try uuid(value.id), campaignID: try uuid(value.campaign_id),
      matchTaskID: try uuid(value.match_task_id), templateID: try optionalUUID(value.template_id),
      templateName: nil, templateVersion: nil,
      requestedCreatorIDs: try value.requested_creator_ids.map(uuid),
      requestedAt: value.requested_at, state: .queued,
      deliveries: try value.deliveries.map {
        try deliverySummary($0, campaignID: value.campaign_id, sendBatchID: value.id)
      })
  }

  static func deliverySummary(
    _ value: Components.Schemas.OutreachDeliverySummary, campaignID: String,
    sendBatchID: String
  ) throws -> Delivery {
    Delivery(
      id: try uuid(value.id), campaignID: try uuid(campaignID),
      sendBatchID: try uuid(sendBatchID),
      creatorID: try uuid(value.creator_id), creator: nil,
      recipientEmail: value.recipient_email, sendState: try sendState(value.send_state.rawValue),
      responseState: try responseState(value.response_state.rawValue),
      resendsDeliveryID: try optionalUUID(value.resends_delivery_id),
      supersededByDeliveryID: nil, isCurrent: nil, templateName: nil, templateVersion: nil,
      renderedSubject: nil, renderedMarkdown: nil, renderedHTML: nil, senderName: nil,
      senderAddress: nil, replyTo: nil, acceptedLabel: nil, declinedLabel: nil,
      smtpFailure: nil, canResend: nil, createdAt: nil, sendingAt: nil, sentAt: nil, failedAt: nil,
      respondedAt: nil, supersededAt: nil)
  }

  private static func analysisJob(
    id: String, profileType profileTypeValue: String, canonicalTargetID: String,
    canonicalURL: String, mode modeValue: String, status statusValue: String, stage: String?,
    completedUnits: Int, totalUnits: Int, retryable: Bool, correlationID: String?,
    profileID: String?, createdAt: Date, updatedAt: Date, startedAt: Date?, completedAt: Date?,
    failure: JobFailure?
  ) throws -> AnalysisJob {
    AnalysisJob(
      id: try uuid(id), profileType: try profileType(profileTypeValue),
      canonicalTargetID: canonicalTargetID, canonicalURL: canonicalURL,
      mode: try analysisMode(modeValue), status: try jobStatus(statusValue),
      stage: try stage.map { try analysisStage($0) }, completedUnits: completedUnits,
      totalUnits: totalUnits, retryable: retryable, correlationID: correlationID,
      profileID: try optionalUUID(profileID), createdAt: createdAt, updatedAt: updatedAt,
      startedAt: startedAt, completedAt: completedAt, failure: failure)
  }

  private static func candidate(_ value: Components.Schemas.MatchResultItem) throws
    -> MatchCandidate
  {
    let c = value.creator
    let b = value.match_brief
    let d = value.dimension_outcomes
    let o = value.outreach
    let preferredContact = c.contact.map { matchContact($0.value1) }
    return MatchCandidate(
      creator: MatchCreatorCard(
        id: try uuid(c.id), name: c.name, youtubeChannelID: c.youtube_channel_id,
        platformAccountID: c.platform_account_id,
        canonicalURL: c.canonical_url, favorite: c.favorite,
        contactAvailable: c.contact_available,
        contact: preferredContact, avatarURL: c.avatar_url,
        performanceSummary: c.performance_summary,
        subscriberCount: c.subscriber_count, recentAverageViews: c.recent_average_views,
        recentMedianViews: c.recent_median_views,
        contacts: matchContacts(c.contacts, fallback: preferredContact)),
      group: try matchGroup(value.result_group.rawValue),
      label: try matchLabel(value.qualitative_label.rawValue),
      dimensionOutcomes: MatchDimensionOutcomes(
        contentFit: d.content_fit, audienceFit: d.audience_fit,
        performanceFit: d.performance_fit, promotionFit: d.promotion_fit,
        brandSafety: d.brand_safety), reasons: value.match_reasons,
      brief: MatchBrief(
        contentFit: briefDimension(b.content_fit), audienceFit: briefDimension(b.audience_fit),
        performanceFit: briefDimension(b.performance_fit),
        promotionFit: briefDimension(b.promotion_fit), brandSafety: briefDimension(b.brand_safety),
        strengths: b.strengths, risks: b.risks, evidence: b.evidence,
        matchReasons: b.match_reasons),
      outreach: MatchOutreach(
        deliveryID: try optionalUUID(o.delivery_id),
        sendState: try o.send_state.map { try sendState($0.rawValue) },
        responseState: try o.response_state.map { try responseState($0.rawValue) }))
  }

  private static func briefDimension(_ value: Components.Schemas.MatchBriefDimension)
    -> MatchBriefDimension
  { MatchBriefDimension(analysis: value.analysis, evidence: value.evidence) }

  private static func matchGame(_ value: Components.Schemas.MatchGameHeader) throws
    -> MatchGameHeader
  {
    MatchGameHeader(
      id: try uuid(value.id), name: value.name, steamAppID: value.steam_app_id,
      canonicalURL: value.canonical_url, coverURL: value.cover_url)
  }

  private static func campaignGame(_ value: Components.Schemas.OutreachCampaignGame) throws
    -> CampaignGame
  {
    CampaignGame(
      id: try uuid(value.id), name: value.name, steamAppID: value.steam_app_id,
      steamURL: value.steam_url, coverURL: value.cover_url)
  }

  private static func campaignMetrics(_ value: Components.Schemas.OutreachCampaignMetrics)
    -> CampaignMetrics
  {
    CampaignMetrics(
      sentCreators: value.sent_creators, accepted: value.accepted, declined: value.declined,
      noResponse: value.no_response, failed: value.failed, responseRate: value.response_rate)
  }

  private static func sendBatch(
    _ value: Components.Schemas.OutreachSendBatchDetail, matchTaskID: UUID
  ) throws
    -> SendBatch
  {
    SendBatch(
      id: try uuid(value.id), campaignID: try uuid(value.campaign_id),
      matchTaskID: matchTaskID,
      templateID: try optionalUUID(value.template_id), templateName: value.template_name,
      templateVersion: value.template_version,
      requestedCreatorIDs: try value.requested_creator_ids.map(uuid),
      requestedAt: value.requested_at, state: try sendBatchState(value.state.rawValue),
      deliveries: try value.deliveries.map(delivery))
  }

  static func delivery(_ value: Components.Schemas.OutreachDeliveryDetail) throws -> Delivery {
    let creator = value.creator
    return Delivery(
      id: try uuid(value.id), campaignID: try uuid(value.campaign_id),
      sendBatchID: try uuid(value.send_batch_id), creatorID: try uuid(creator.id),
      creator: OutreachCreator(
        id: try uuid(creator.id), name: creator.name,
        youtubeChannelID: creator.youtube_channel_id,
        platformAccountID: creator.platform_account_id ?? creator.youtube_channel_id ?? "",
        canonicalURL: creator.canonical_url,
        avatarURL: creator.avatar_url), recipientEmail: value.recipient_email,
      sendState: try sendState(value.send_state.rawValue),
      responseState: try responseState(value.response_state.rawValue),
      resendsDeliveryID: try optionalUUID(value.resends_delivery_id),
      supersededByDeliveryID: try optionalUUID(value.superseded_by_delivery_id),
      isCurrent: value.is_current, templateName: value.template_name,
      templateVersion: value.template_version, renderedSubject: value.rendered_subject,
      renderedMarkdown: value.rendered_markdown, renderedHTML: value.rendered_html,
      senderName: value.sender_name, senderAddress: value.sender_address, replyTo: value.reply_to,
      acceptedLabel: value.accepted_label, declinedLabel: value.declined_label,
      smtpFailure: value.smtp_error.map {
        SMTPFailure(
          code: $0.value1.code.rawValue, message: $0.value1.message.rawValue,
          retryable: $0.value1.retryable)
      }, canResend: value.can_resend, createdAt: value.created_at,
      sendingAt: value.sending_at, sentAt: value.sent_at,
      failedAt: value.failed_at, respondedAt: value.responded_at,
      supersededAt: value.superseded_at)
  }

  private static func contact(_ value: Components.Schemas.CreatorContactResponse?)
    -> CreatorContact?
  {
    value.map(contact)
  }

  private static func contact(_ value: Components.Schemas.CreatorContactResponse)
    -> CreatorContact
  {
    CreatorContact(
      email: value.email, availability: value.source == "manual" ? .manual : .discovered,
      source: value.source, sourceURL: value.source_url,
      validationState: value.validation_state, purpose: value.purpose)
  }

  private static func contacts(
    _ values: [Components.Schemas.CreatorContactResponse]?, fallback: CreatorContact?
  ) -> [CreatorContact] {
    guard let values else { return fallback.map { [$0] } ?? [] }
    return values.map(contact)
  }

  private static func matchContact(_ value: Components.Schemas.MatchCreatorContact)
    -> MatchCreatorContact
  {
    MatchCreatorContact(
      email: value.email, source: value.source, sourceURL: value.source_url,
      validationState: value.validation_state, purpose: value.purpose)
  }

  private static func matchContacts(
    _ values: [Components.Schemas.MatchCreatorContact]?, fallback: MatchCreatorContact?
  ) -> [MatchCreatorContact] {
    guard let values else { return fallback.map { [$0] } ?? [] }
    return values.map(matchContact)
  }

  private static func json(_ value: Components.Schemas.PublicJSONObject) throws -> JSONObject {
    try value.additionalProperties.value.mapValues(jsonValue)
  }

  private static func jsonValue(_ value: (any Sendable)?) throws -> JSONValue {
    guard let value, !(value is NSNull) else { return .null }
    switch value {
    case let value as Bool: return .boolean(value)
    case let value as Int: return .integer(value)
    case let value as Double: return .number(value)
    case let value as String: return .string(value)
    case let value as [(any Sendable)?]: return .array(try value.map(jsonValue))
    case let value as [String: (any Sendable)?]:
      return .object(try value.mapValues(jsonValue))
    default: throw APIError.invalidResponse
    }
  }

  private static func uuid(_ value: String) throws -> UUID {
    guard let result = UUID(uuidString: value) else { throw APIError.invalidResponse }
    return result
  }

  private static func optionalUUID(_ value: String?) throws -> UUID? {
    try value.map(uuid)
  }

  private static func profileType(_ value: String) throws -> ProfileType {
    guard let result = ProfileType(rawValue: value) else { throw APIError.invalidResponse }
    return result
  }

  private static func analysisMode(_ value: String) throws -> AnalysisMode {
    guard let result = AnalysisMode(rawValue: value) else { throw APIError.invalidResponse }
    return result
  }

  private static func jobStatus(_ value: String) throws -> JobStatus {
    guard let result = JobStatus(rawValue: value) else { throw APIError.invalidResponse }
    return result
  }

  private static func analysisStage(_ value: String) throws -> AnalysisStage {
    let normalized = value == "fetching_data" ? "fetchingData" : value
    guard let result = AnalysisStage(rawValue: normalized) else { throw APIError.invalidResponse }
    return result
  }

  private static func matchStage(_ value: String) throws -> MatchStage {
    guard let result = MatchStage(rawValue: value) else { throw APIError.invalidResponse }
    return result
  }

  private static func resultState(_ value: String) throws -> MatchResultState {
    let normalized = value == "no_suitable_creators" ? "noSuitableCreators" : value
    guard let result = MatchResultState(rawValue: normalized) else {
      throw APIError.invalidResponse
    }
    return result
  }

  private static func matchGroup(_ value: String) throws -> MatchGroup {
    guard let result = MatchGroup(rawValue: value) else { throw APIError.invalidResponse }
    return result
  }

  private static func matchLabel(_ value: String) throws -> MatchLabel {
    switch value {
    case "Strong Match": return .strong
    case "Good Match": return .good
    case "Limited Match": return .limited
    default: throw APIError.invalidResponse
    }
  }

  private static func campaignState(_ value: String) throws -> CampaignState {
    let normalized = value == "not_started" ? "notStarted" : value
    guard let result = CampaignState(rawValue: normalized) else { throw APIError.invalidResponse }
    return result
  }

  private static func sendBatchState(_ value: String) throws -> SendBatchState {
    let normalized = value == "partially_failed" ? "partiallyFailed" : value
    guard let result = SendBatchState(rawValue: normalized) else { throw APIError.invalidResponse }
    return result
  }

  private static func sendState(_ value: String) throws -> SendState {
    let normalized = value == "not_sent" ? "notSent" : value
    guard let result = SendState(rawValue: normalized) else { throw APIError.invalidResponse }
    return result
  }

  private static func responseState(_ value: String) throws -> ResponseState {
    let normalized = value == "no_response" ? "noResponse" : value
    guard let result = ResponseState(rawValue: normalized) else { throw APIError.invalidResponse }
    return result
  }

  private static func smtpEncryption(_ value: String) throws -> SMTPEncryption {
    let normalized = value == "starttls" ? "startTLS" : value
    guard let result = SMTPEncryption(rawValue: normalized) else { throw APIError.invalidResponse }
    return result
  }

  private static func connectionTestStatus(_ value: String?) -> ConnectionTestStatus {
    switch value {
    case "success": .success
    case "failure": .failed
    default: .notTested
    }
  }
}
