import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing

@testable import FindMeGamerCore

@Suite(.serialized) struct OpenAPIServiceTests {
  @Test func profileAndFavoriteUsePluralCollectionPaths() async throws {
    let transport = RecordingTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "cid" })
    let gameID = id("10000000-0000-4000-8000-000000000001")
    let creatorID = id("40000000-0000-4000-8000-000000000001")

    _ = try await service.profile(type: .game, id: gameID)
    _ = try await service.profile(type: .creator, id: creatorID)
    _ = try await service.setFavorite(type: .game, id: gameID, favorite: true)
    _ = try await service.setFavorite(type: .creator, id: creatorID, favorite: true)

    let requests = await transport.requests
    #expect(
      requests.filter { $0.operationID == "getProfile" }.map(\.path) == [
        "/api/v1/profiles/games/\(gameID.uuidString.lowercased())",
        "/api/v1/profiles/creators/\(creatorID.uuidString.lowercased())",
      ])
    #expect(
      requests.filter { $0.operationID == "setProfileFavorite" }.map(\.path) == [
        "/api/v1/profiles/games/\(gameID.uuidString.lowercased())/favorite",
        "/api/v1/profiles/creators/\(creatorID.uuidString.lowercased())/favorite",
      ])
  }

  @Test func completeProtocolUsesGeneratedClientAndRoutesEveryMethod() async throws {
    let transport = RecordingTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "WORKSPACE-KEY-CANARY" }, correlationIDProvider: { "correlation-fixed" })
    let api: any APIService = service
    let profileID = id("10000000-0000-4000-8000-000000000001")
    let matchID = id("30000000-0000-4000-8000-000000000001")
    let creatorID = id("40000000-0000-4000-8000-000000000001")
    let campaignID = id("60000000-0000-4000-8000-000000000001")
    let templateID = id("80000000-0000-4000-8000-000000000001")
    let deliveryID = id("50000000-0000-4000-8000-000000000001")

    #expect(try await api.validateSession().workspaceName == "Demo")
    #expect(
      try await api.listJobs(changedAfter: "opaque:change", status: .running).cursor
        == "opaque:next")
    guard
      case .existingProfile(let existing) = try await api.createAnalysisJob(
        AnalysisRequest(url: "https://store.steampowered.com/app/730", profileType: .game),
        idempotencyKey: "idem-analysis-create")
    else {
      Issue.record("Expected existing profile")
      return
    }
    #expect(existing.profileID == profileID)
    #expect(
      try await api.retryAnalysisJob(id: profileID, idempotencyKey: "idem-analysis-retry").status
        == .running)
    #expect(
      try await api.listProfiles(
        type: .game, query: "garden search", onlyCollection: true, cursor: "cursor-game", limit: 25
      ).items.count == 1)
    #expect(
      try await api.listProfiles(
        type: .creator, query: "channel search", onlyCollection: false,
        cursor: "cursor-creator", limit: 20
      ).items.count == 1)
    guard case .game = try await api.profile(type: .game, id: profileID) else {
      Issue.record("Expected Game profile")
      return
    }
    guard case .creator = try await api.profile(type: .creator, id: creatorID) else {
      Issue.record("Expected Creator profile")
      return
    }
    guard case .game = try await api.setFavorite(type: .game, id: profileID, favorite: true)
    else {
      Issue.record("Expected Game card")
      return
    }
    guard case .creator = try await api.setFavorite(type: .creator, id: creatorID, favorite: false)
    else {
      Issue.record("Expected Creator card")
      return
    }
    #expect(
      try await api.updateCreatorManual(id: creatorID, email: nil, notes: "manual notes")
        .manualNotes == "manual notes")
    #expect(
      try await api.updateCreatorManual(
        id: creatorID, email: "creator@example.com", notes: "manual notes"
      ).contact?.email == "creator@example.com")
    #expect(
      try await api.createMatch(gameID: profileID, idempotencyKey: "idem-match-create").id
        == matchID)
    #expect(try await api.listMatches(cursor: "cursor-match").items.count == 1)
    #expect(try await api.match(id: matchID).recommendedMatches.first?.creator.name == "Creator")
    #expect(try await api.retryMatch(id: matchID, idempotencyKey: "idem-match-retry").id == matchID)
    #expect(try await api.listCampaigns(cursor: "cursor-campaign").items.count == 1)
    #expect(try await api.campaign(id: campaignID).id == campaignID)
    #expect(try await api.listTemplates().count == 1)

    let newTemplate = TemplateDraft(
      name: "Launch", subjectTemplate: "Hi", bodyMarkdown: "Body",
      acceptedLabel: "Yes", declinedLabel: "No")
    #expect(try await api.saveTemplate(newTemplate).id == templateID)
    let existingTemplate = TemplateDraft(
      id: templateID, name: "Launch 2", subjectTemplate: "Hi", bodyMarkdown: "Body")
    #expect(try await api.saveTemplate(existingTemplate).name == "Launch")
    #expect(try await api.duplicateTemplate(id: templateID).id == templateID)
    #expect(try await api.setDefaultTemplate(id: templateID).isDefault)
    try await api.deleteTemplate(id: templateID)
    #expect(try await api.previewTemplate(existingTemplate).subject == "Hello")

    let sendDraft = SendBatchDraft(
      matchTaskID: matchID, creatorIDs: [creatorID],
      recipientSelections: [
        OutreachRecipientSelection(creatorID: creatorID, email: "selected@example.com")
      ],
      templateID: templateID,
      subjectOverride: "Subject", bodyMarkdownOverride: "Body")
    #expect(try await api.previewSendBatch(sendDraft).first?.creatorID == creatorID)
    #expect(
      try await api.createSendBatch(sendDraft, idempotencyKey: "idem-send-batch").id
        == id("70000000-0000-4000-8000-000000000001"))
    #expect(
      try await api.resendDelivery(id: deliveryID, idempotencyKey: "idem-resend").id == deliveryID)
    #expect(try await api.smtpSettings().configured)
    let smtpDraft = SMTPSettingsDraft(
      host: "smtp.example.com", port: 587, encryption: .startTLS,
      username: "mailer@example.com", password: "SMTP-PASSWORD-CANARY",
      fromName: "Find Me Gamer", replyTo: "reply@example.com", emailsPerMinute: 10)
    #expect(try await api.saveSMTPSettings(smtpDraft).configured)
    #expect(try await api.testSMTPConnection(nil).succeeded)
    #expect(try await api.sendSMTPTest(to: "test@example.com").succeeded)
    #expect(try await api.sharedSettings().gameIntervalDays == 30)
    #expect(
      try await api.saveReanalysis(ReanalysisDraft(gameIntervalDays: 14, creatorIntervalDays: 21))
        .creatorIntervalDays == 30)
    #expect(try await api.connection(.googleAI).configured)
    #expect(
      try await api.replaceConnection(.googleAI, secret: "CONNECTION-SECRET-CANARY").configured)
    #expect(try await api.testConnection(.googleAI).succeeded)

    let requests = await transport.requests
    #expect(requests.count == 37)
    #expect(requests.allSatisfy { $0.authorization == "Bearer WORKSPACE-KEY-CANARY" })
    #expect(requests.allSatisfy { $0.correlationID == "correlation-fixed" })
    for key in [
      "idem-analysis-create", "idem-analysis-retry", "idem-match-create", "idem-match-retry",
      "idem-send-batch", "idem-resend",
    ] {
      #expect(requests.filter { $0.idempotencyKey == key }.count == 1)
    }
    #expect(requests.contains { $0.operationID == "createOutreachSendBatch" })
    #expect(!requests.contains { $0.operationID == "createSendBatch" })
    let googleAIRequests = requests.filter {
      $0.path == "/api/v1/settings/connections/google_ai"
    }
    #expect(googleAIRequests.map(\.method) == ["GET", "PUT", "POST"])
    #expect(
      googleAIRequests.map(\.operationID) == [
        "getConnectionStatus", "replaceConnectionSecret", "testConnection",
      ])
    #expect(
      requests.contains {
        $0.path.contains("query=garden%20search") && $0.path.contains("only_collection=true")
      })
    #expect(
      requests.contains {
        $0.path.contains("changed_after=opaque%3Achange") && $0.path.contains("status=running")
      })
    let manualBodies = try requests.filter { $0.operationID == "updateCreatorManual" }.map {
      try #require(
        JSONSerialization.jsonObject(with: Data($0.body.utf8)) as? [String: Any])
    }
    #expect(manualBodies.count == 2)
    #expect(manualBodies.contains { $0["contact_email"] == nil })
    #expect(manualBodies.contains { $0["contact_email"] as? String == "creator@example.com" })
    let sendBodies = try requests.filter {
      $0.operationID == "previewOutreachSendBatch"
        || $0.operationID == "createOutreachSendBatch"
    }.map {
      try #require(JSONSerialization.jsonObject(with: Data($0.body.utf8)) as? [String: Any])
    }
    #expect(sendBodies.count == 2)
    #expect(
      sendBodies.allSatisfy { body in
        guard let selections = body["recipient_selections"] as? [[String: Any]],
          selections.count == 1
        else { return false }
        return selections[0]["creator_id"] as? String == creatorID.uuidString
          && selections[0]["email"] as? String == "selected@example.com"
      })

    let descriptions = [
      String(reflecting: try await api.smtpSettings()),
      String(reflecting: try await api.connection(.googleAI)),
    ].joined()
    #expect(!descriptions.contains("SMTP-PASSWORD-CANARY"))
    #expect(!descriptions.contains("CONNECTION-SECRET-CANARY"))
    #expect(!descriptions.contains("WORKSPACE-KEY-CANARY"))
  }

  @Test func emptyRecipientSelectionsAreOmittedFromTheWireRequest() async throws {
    let transport = RecordingTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "cid" })
    let draft = SendBatchDraft(
      matchTaskID: id("30000000-0000-4000-8000-000000000001"),
      creatorIDs: [id("40000000-0000-4000-8000-000000000001")])

    _ = try await service.previewSendBatch(draft)

    let request = try #require(await transport.requests.first)
    let body = try #require(
      JSONSerialization.jsonObject(with: Data(request.body.utf8)) as? [String: Any])
    #expect(body["recipient_selections"] == nil)
  }

  @Test func unsavedTemplatePreviewFailsWithoutTransport() async throws {
    let transport = RecordingTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "cid" })
    do {
      _ = try await service.previewTemplate(
        TemplateDraft(name: "Unsaved", subjectTemplate: "Subject", bodyMarkdown: "Body"))
      Issue.record("Expected a local failure")
    } catch let error as APIError {
      #expect(error.code == "template_not_saved")
      #expect(!error.retryable)
    }
    #expect(await transport.requests.isEmpty)
  }

  @Test func missingKeyFailsBeforeTransportWithoutEchoingCredential() async throws {
    let transport = RecordingTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "   " }, correlationIDProvider: { "cid" })
    do {
      _ = try await service.validateSession()
      Issue.record("Expected missing-key failure")
    } catch let error as APIError {
      #expect(error.code == "missing_workspace_key")
      #expect(!String(describing: error).contains("   "))
    }
    #expect(await transport.requests.isEmpty)
  }

  @Test func unsavedSMTPDraftTestFailsLocallyWithoutTransport() async throws {
    let transport = RecordingTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "cid" })
    let draft = SMTPSettingsDraft(
      host: "smtp.example.com", username: "mailer@example.com",
      password: "SMTP-PASSWORD-CANARY", fromName: "Find Me Gamer",
      replyTo: "reply@example.com")
    do {
      _ = try await service.testSMTPConnection(draft)
      Issue.record("Expected unsupported unsaved-draft failure")
    } catch let error as APIError {
      #expect(error.code == "smtp_draft_test_unsupported")
      #expect(error.message == "Save the email settings before testing the connection.")
      #expect(!error.retryable)
      #expect(!String(describing: error).contains("SMTP-PASSWORD-CANARY"))
    }
    #expect(await transport.requests.isEmpty)
  }

  @Test(arguments: [401, 409, 422, 500])
  func mapsGlobalErrorEnvelopeBeforeGeneratedDecoding(status: Int) async throws {
    let transport = RecordingTransport(errorStatus: status)
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "WORKSPACE-KEY-CANARY" }, correlationIDProvider: { "request-cid" })
    do {
      _ = try await service.validateSession()
      Issue.record("Expected API error")
    } catch let error as APIError {
      #expect(error.code == "backend_\(status)")
      #expect(error.message == "Safe backend message")
      #expect(error.retryable == (status == 500))
      #expect(error.correlationID == "response-cid")
      #expect(!String(describing: error).contains("WORKSPACE-KEY-CANARY"))
      #expect(!String(describing: error).contains("RAW-SECRET-CANARY"))
    }
    #expect(await transport.requests.count == 1)
  }

  @Test func malformedHTTPErrorUsesSafeStableFallback() async throws {
    let transport = RecordingTransport(errorStatus: 503, malformedError: true)
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "request-cid" })
    do {
      _ = try await service.validateSession()
      Issue.record("Expected API error")
    } catch let error as APIError {
      #expect(error.code == "http_503")
      #expect(error.retryable)
      #expect(error.message == "The server could not complete the request.")
      #expect(!String(describing: error).contains("RAW-SECRET-CANARY"))
    }
  }

  @Test func malformedSuccessMapsToSafeInvalidResponse() async throws {
    let transport = RecordingTransport(malformedSuccess: true)
    let service = OpenAPIService(
      baseURL: URL(string: "https://api.example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "request-cid" })
    do {
      _ = try await service.validateSession()
      Issue.record("Expected invalid-response failure")
    } catch let error as APIError {
      #expect(error == .invalidResponse)
      #expect(!String(describing: error).contains("RAW-SECRET-CANARY"))
    }
  }

  @Test func rfc3339TranscoderAcceptsNanosecondsAndTimezoneOffsets() throws {
    let transcoder = RFC3339DateTranscoder()

    let offsetDate = try transcoder.decode("2026-09-04T11:50:08.123456789+08:00")
    let utcDate = try transcoder.decode("2026-09-04T03:50:08.123456789Z")

    #expect(offsetDate == utcDate)
    #expect(try transcoder.encode(offsetDate) == "2026-09-04T03:50:08Z")
  }
}

private actor RecordingTransport: ClientTransport {
  struct Request: Sendable {
    let operationID: String
    let method: String
    let path: String
    let authorization: String?
    let correlationID: String?
    let idempotencyKey: String?
    let body: String
  }

  private(set) var requests: [Request] = []
  private let errorStatus: Int?
  private let malformedError: Bool
  private let malformedSuccess: Bool

  init(errorStatus: Int? = nil, malformedError: Bool = false, malformedSuccess: Bool = false) {
    self.errorStatus = errorStatus
    self.malformedError = malformedError
    self.malformedSuccess = malformedSuccess
  }

  func send(
    _ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String
  ) async throws -> (HTTPResponse, HTTPBody?) {
    let bodyData: Data
    if let body {
      bodyData = try await Data(collecting: body, upTo: 1_000_000)
    } else {
      bodyData = Data()
    }
    requests.append(
      Request(
        operationID: operationID, method: request.method.rawValue,
        path: request.path ?? "", authorization: request.headerFields[.authorization],
        correlationID: request.headerFields[HTTPField.Name("X-Correlation-ID")!],
        idempotencyKey: request.headerFields[HTTPField.Name("Idempotency-Key")!],
        body: String(decoding: bodyData, as: UTF8.self)))

    if let errorStatus {
      var fields = HTTPFields()
      fields[.contentType] = "application/json"
      fields[HTTPField.Name("X-Correlation-ID")!] = "response-cid"
      let raw =
        malformedError
        ? #"{"raw":"RAW-SECRET-CANARY"}"#
        : """
        {"error":{"code":"backend_\(errorStatus)","message":"Safe backend message","retryable":\(errorStatus == 500),"correlation_id":"body-cid","ignored":"RAW-SECRET-CANARY"}}
        """
      return (
        HTTPResponse(status: HTTPResponse.Status(code: errorStatus), headerFields: fields),
        HTTPBody(Data(raw.utf8))
      )
    }

    if malformedSuccess {
      var fields = HTTPFields()
      fields[.contentType] = "application/json"
      return (
        HTTPResponse(status: .ok, headerFields: fields),
        HTTPBody(Data(#"{"raw":"RAW-SECRET-CANARY"}"#.utf8))
      )
    }

    let fixture = try responseFixture(operationID: operationID, request: request, body: bodyData)
    var fields = HTTPFields()
    if fixture.status != 204 { fields[.contentType] = "application/json" }
    return (
      HTTPResponse(status: HTTPResponse.Status(code: fixture.status), headerFields: fields),
      fixture.body.map { HTTPBody(Data($0.utf8)) }
    )
  }
}

private func responseFixture(operationID: String, request: HTTPRequest, body: Data) throws -> (
  status: Int, body: String?
) {
  let creatorRoute =
    (request.path ?? "").contains("/creators")
    || (request.path ?? "").contains("/creator/")
    || operationID == "updateCreatorManual"
  switch operationID {
  case "validateSession": return (200, sessionFixture)
  case "listJobs": return (200, changedJobsFixture)
  case "createAnalysisJob": return (200, existingProfileFixture)
  case "retryAnalysisJob": return (200, analysisJobFixture)
  case "listGameProfiles": return (200, "{\"items\":[\(gameCardFixture)],\"next_cursor\":null}")
  case "listCreatorProfiles":
    return (200, "{\"items\":[\(creatorCardFixture)],\"next_cursor\":\"opaque-next\"}")
  case "getProfile": return (200, creatorRoute ? creatorDetailFixture : gameDetailFixture)
  case "setProfileFavorite": return (200, creatorRoute ? creatorCardFixture : gameCardFixture)
  case "updateCreatorManual":
    let raw = String(decoding: body, as: UTF8.self)
    return (
      200,
      raw.contains("creator@example.com")
        ? creatorDetailFixture : creatorDetailWithoutContactFixture
    )
  case "createMatch", "retryMatch": return (202, matchSummaryFixture)
  case "listMatches":
    return (200, "{\"items\":[\(matchSummaryFixture)],\"cursor\":\"next\",\"has_more\":true}")
  case "getMatch": return (200, matchDetailFixture)
  case "listOutreachCampaigns":
    return (200, "{\"items\":[\(campaignSummaryFixture)],\"cursor\":null,\"has_more\":false}")
  case "getOutreachCampaign": return (200, campaignDetailFixture)
  case "listOutreachTemplates": return (200, "{\"items\":[\(templateFixture)]}")
  case "createOutreachTemplate": return (201, templateFixture)
  case "updateOutreachTemplate", "duplicateOutreachTemplate", "setDefaultOutreachTemplate":
    return (operationID == "duplicateOutreachTemplate" ? 201 : 200, templateFixture)
  case "deleteOutreachTemplate": return (204, nil)
  case "previewOutreachTemplate": return (200, renderedFixture)
  case "previewOutreachSendBatch": return (200, sendBatchPreviewFixture)
  case "createOutreachSendBatch": return (201, sendBatchResponseFixture)
  case "resendOutreachDelivery": return (201, sendBatchResponseFixture)
  case "getOutreachSMTPSettings", "updateOutreachSMTPSettings": return (200, smtpFixture)
  case "testOutreachSMTPConnection", "sendOutreachSMTPTestEmail":
    return (200, testResultFixture)
  case "getReanalysisSettings", "updateReanalysisSettings": return (200, reanalysisFixture)
  case "getConnectionStatus", "replaceConnectionSecret", "testConnection":
    return (200, connectionFixture)
  default: throw APIError(code: "missing_fixture", message: operationID, retryable: false)
  }
}

private func id(_ raw: String) -> UUID { UUID(uuidString: raw)! }

private let sessionFixture =
  #"{"workspace_name":"Demo","api_version":"v1","service_connections":{"deepseek":true,"steam":true}}"#
private let existingProfileFixture =
  #"{"outcome":"existing_profile","existing_profile_id":"10000000-0000-4000-8000-000000000001","target_type":"game","canonical_target_id":"730","canonical_url":"https://store.steampowered.com/app/730"}"#
private let analysisJobFixture =
  #"{"outcome":"job","id":"10000000-0000-4000-8000-000000000001","target_type":"game","canonical_target_id":"730","canonical_url":"https://store.steampowered.com/app/730","mode":"reanalyze","status":"running","stage":"analyzing","completed_units":1,"total_units":2,"retryable":false,"correlation_id":null,"profile_id":null,"created_at":"2026-09-03T00:00:00Z","updated_at":"2026-09-03T00:01:00Z","started_at":"2026-09-03T00:00:01Z","completed_at":null,"error":null}"#
private let changedJobsFixture =
  #"{"items":[],"cursor":"opaque:next","has_more":false,"affected_profile_ids":[]}"#
private let gameCardFixture =
  #"{"type":"game","id":"10000000-0000-4000-8000-000000000001","name":"Game","steam_app_id":"730","canonical_url":"https://store.steampowered.com/app/730","favorite":true,"current_facts":{},"brief":{},"source_status":{},"last_analyzed_at":null,"next_analysis_at":null}"#
private let gameDetailFixture =
  #"{"type":"game","id":"10000000-0000-4000-8000-000000000001","name":"Game","steam_app_id":"730","canonical_url":"https://store.steampowered.com/app/730","favorite":true,"current_facts":{},"brief":{},"source_status":{},"last_analyzed_at":null,"next_analysis_at":null,"analysis":{},"model_metadata":{},"prompt_metadata":{}}"#
private let creatorCardFixture =
  #"{"type":"creator","id":"40000000-0000-4000-8000-000000000001","name":"Creator","platform": "youtube", "platform_account_id": "UC-1", "youtube_channel_id": "UC-1","canonical_url":"https://youtube.com/@creator","favorite":false,"current_facts":{},"brief":{},"source_status":{},"last_analyzed_at":null,"next_analysis_at":null,"contact":{"email":"creator@example.com","source":"manual","source_url":null,"validation_state":"valid"}}"#
private let creatorDetailFixture =
  #"{"type":"creator","id":"40000000-0000-4000-8000-000000000001","name":"Creator","platform": "youtube", "platform_account_id": "UC-1", "youtube_channel_id": "UC-1","canonical_url":"https://youtube.com/@creator","favorite":false,"current_facts":{},"brief":{},"source_status":{},"last_analyzed_at":null,"next_analysis_at":null,"contact":{"email":"creator@example.com","source":"manual","source_url":null,"validation_state":"valid"},"manual_notes":"manual notes","analysis":{},"model_metadata":{},"prompt_metadata":{}}"#
private let creatorDetailWithoutContactFixture =
  #"{"type":"creator","id":"40000000-0000-4000-8000-000000000001","name":"Creator","platform": "youtube", "platform_account_id": "UC-1", "youtube_channel_id": "UC-1","canonical_url":"https://youtube.com/@creator","favorite":false,"current_facts":{},"brief":{},"source_status":{},"last_analyzed_at":null,"next_analysis_at":null,"contact":null,"manual_notes":"manual notes","analysis":{},"model_metadata":{},"prompt_metadata":{}}"#
private let matchGameFixture =
  #"{"id":"10000000-0000-4000-8000-000000000001","name":"Game","steam_app_id":"730","canonical_url":"https://store.steampowered.com/app/730","cover_url":null}"#
private let matchSummaryFixture =
  "{\"id\":\"30000000-0000-4000-8000-000000000001\",\"game\":\(matchGameFixture),\"status\":\"succeeded\",\"stage\":\"ranking\",\"completed_units\":1,\"total_units\":1,\"result_count\":1,\"retryable\":false,\"error\":null,\"correlation_id\":null,\"supersedes_id\":null,\"created_at\":\"2026-09-03T00:00:00Z\",\"updated_at\":\"2026-09-03T00:01:00Z\",\"started_at\":null,\"completed_at\":null}"
private let matchItemFixture =
  #"{"creator":{"id":"40000000-0000-4000-8000-000000000001","name":"Creator","platform": "youtube", "platform_account_id": "UC-1", "youtube_channel_id": "UC-1","canonical_url":"https://youtube.com/@creator","favorite":false,"contact_available":false,"contact":null,"avatar_url":null,"performance_summary":null,"subscriber_count":null,"recent_average_views":null,"recent_median_views":null},"result_group":"recommended","qualitative_label":"Good Match","dimension_outcomes":{"content_fit":"Good","audience_fit":"Good","performance_fit":"Good","promotion_fit":"Good","brand_safety":"Good"},"match_reasons":["Fit"],"match_brief":{"content_fit":{"analysis":"Good","evidence":[]},"audience_fit":{"analysis":"Good","evidence":[]},"performance_fit":{"analysis":"Good","evidence":[]},"promotion_fit":{"analysis":"Good","evidence":[]},"brand_safety":{"analysis":"Good","evidence":[]},"strengths":[],"risks":[],"evidence":[],"match_reasons":["Fit"]},"outreach":{"delivery_id":null,"send_state":null,"response_state":null}}"#
private let matchDetailFixture =
  "{\"id\":\"30000000-0000-4000-8000-000000000001\",\"game\":\(matchGameFixture),\"status\":\"succeeded\",\"stage\":\"ranking\",\"completed_units\":1,\"total_units\":1,\"result_count\":1,\"retryable\":false,\"error\":null,\"correlation_id\":null,\"supersedes_id\":null,\"created_at\":\"2026-09-03T00:00:00Z\",\"updated_at\":\"2026-09-03T00:01:00Z\",\"started_at\":null,\"completed_at\":null,\"result_state\":\"available\",\"recommended_matches\":[\(matchItemFixture)],\"other_matches\":[]}"
private let campaignGameFixture =
  #"{"id":"10000000-0000-4000-8000-000000000001","name":"Game","steam_app_id":"730","steam_url":"https://store.steampowered.com/app/730","cover_url":null}"#
private let metricsFixture =
  #"{"sent_creators":1,"accepted":0,"declined":0,"no_response":1,"failed":0,"response_rate":0}"#
private let campaignSummaryFixture =
  "{\"id\":\"60000000-0000-4000-8000-000000000001\",\"match_task_id\":\"30000000-0000-4000-8000-000000000001\",\"game\":\(campaignGameFixture),\"state\":\"completed\",\"send_batch_count\":0,\"metrics\":\(metricsFixture),\"created_at\":\"2026-09-03T00:00:00Z\",\"latest_activity_at\":\"2026-09-03T00:01:00Z\"}"
private let campaignDetailFixture =
  "{\"id\":\"60000000-0000-4000-8000-000000000001\",\"match_task_id\":\"30000000-0000-4000-8000-000000000001\",\"game\":\(campaignGameFixture),\"state\":\"completed\",\"send_batch_count\":0,\"metrics\":\(metricsFixture),\"created_at\":\"2026-09-03T00:00:00Z\",\"latest_activity_at\":\"2026-09-03T00:01:00Z\",\"send_batches\":[]}"
private let templateFixture =
  #"{"id":"80000000-0000-4000-8000-000000000001","name":"Launch","version":2,"subject_template":"Hello","body_markdown":"Body","accepted_label":"Yes","declined_label":"No","is_default":true,"created_at":"2026-09-03T00:00:00Z","updated_at":"2026-09-03T00:01:00Z"}"#
private let renderedFixture = #"{"subject":"Hello","markdown":"Body","html":"<p>Body</p>"}"#
private let sendBatchPreviewFixture =
  #"{"match_task_id":"30000000-0000-4000-8000-000000000001","template_id":"80000000-0000-4000-8000-000000000001","template_name":"Launch","template_version":2,"items":[{"creator_id":"40000000-0000-4000-8000-000000000001","creator_name":"Creator","recipient_email":"creator@example.com","subject":"Hello","markdown":"Body","html":"<p>Body</p>"}]}"#
private let sendBatchResponseFixture =
  #"{"id":"70000000-0000-4000-8000-000000000001","campaign_id":"60000000-0000-4000-8000-000000000001","match_task_id":"30000000-0000-4000-8000-000000000001","template_id":"80000000-0000-4000-8000-000000000001","requested_creator_ids":["40000000-0000-4000-8000-000000000001"],"requested_at":"2026-09-03T00:00:00Z","state":"queued","deliveries":[{"id":"50000000-0000-4000-8000-000000000001","creator_id":"40000000-0000-4000-8000-000000000001","recipient_email":"creator@example.com","send_state":"queued","response_state":"no_response","resends_delivery_id":null}]}"#
private let deliveryFixture =
  #"{"id":"50000000-0000-4000-8000-000000000001","campaign_id":"60000000-0000-4000-8000-000000000001","send_batch_id":"70000000-0000-4000-8000-000000000001","creator":{"id":"40000000-0000-4000-8000-000000000001","name":"Creator","platform": "youtube", "platform_account_id": "UC-1", "youtube_channel_id": "UC-1","canonical_url":"https://youtube.com/@creator","avatar_url":null},"recipient_email":"creator@example.com","send_state":"sent","response_state":"no_response","resends_delivery_id":null,"superseded_by_delivery_id":null,"is_current":true,"template_name":"Launch","template_version":2,"rendered_subject":"Hello","rendered_markdown":"Body","rendered_html":"<p>Body</p>","sender_name":"Sender","sender_address":"sender@example.com","reply_to":"reply@example.com","accepted_label":"Yes","declined_label":"No","smtp_error":null,"can_resend":true,"created_at":"2026-09-03T00:00:00Z","sending_at":null,"sent_at":"2026-09-03T00:01:00Z","failed_at":null,"responded_at":null,"superseded_at":null}"#
private let smtpFixture =
  #"{"configured":true,"host":"smtp.example.com","port":587,"encryption":"starttls","username":"mailer@example.com","from_name":"Find Me Gamer","reply_to":"reply@example.com","emails_per_minute":10,"last_test_status":"success","last_tested_at":"2026-09-03T00:00:00Z"}"#
private let testResultFixture =
  #"{"succeeded":true,"last_test_status":"success","last_tested_at":"2026-09-03T00:00:00Z"}"#
private let reanalysisFixture = #"{"game_interval_days":30,"creator_interval_days":30}"#
private let connectionFixture =
  #"{"configured":true,"last_test_status":"success","last_tested_at":"2026-09-04T03:50:08.619034Z"}"#
