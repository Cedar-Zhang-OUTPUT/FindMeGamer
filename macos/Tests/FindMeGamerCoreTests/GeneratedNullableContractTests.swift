import CryptoKit
import FindMeGamerAPI
import Foundation
import Testing

@Test func generatedAnalysisJobRetainsNullableFields() throws {
  let job = try decodeGenerated(
    Components.Schemas.AnalysisJobResponse.self,
    json: [
      "id": "00000000-0000-4000-8000-000000000001",
      "target_type": "game",
      "canonical_target_id": "730",
      "canonical_url": "https://store.steampowered.com/app/730",
      "mode": "reanalyze",
      "status": "queued",
      "stage": NSNull(),
      "completed_units": 0,
      "total_units": 4,
      "retryable": false,
      "correlation_id": NSNull(),
      "profile_id": NSNull(),
      "created_at": "2026-09-03T00:00:00Z",
      "updated_at": "2026-09-03T00:00:00Z",
      "started_at": NSNull(),
      "completed_at": NSNull(),
      "error": NSNull(),
    ]
  )

  #expect(job.stage == nil)
  #expect(job.correlation_id == nil)
  #expect(job.profile_id == nil)
  #expect(job.started_at == nil)
  #expect(job.completed_at == nil)
  #expect(job.error == nil)
}

@Test func generatedMatchOutreachAcceptsNullAndValueDeliveryIDs() throws {
  let empty = try decodeGenerated(
    Components.Schemas.MatchOutreachState.self,
    json: [
      "delivery_id": NSNull(),
      "send_state": "not_sent",
      "response_state": "no_response",
    ]
  )
  let sent = try decodeGenerated(
    Components.Schemas.MatchOutreachState.self,
    json: [
      "delivery_id": "00000000-0000-4000-8000-000000000002",
      "send_state": "sent",
      "response_state": "accepted",
    ]
  )

  #expect(empty.delivery_id == nil)
  #expect(sent.delivery_id == "00000000-0000-4000-8000-000000000002")
}

@Test func generatedMatchResultRemainsDecodable() throws {
  let dimension = ["analysis": "Fits", "evidence": ["Public evidence"]] as [String: Any]
  let item = try decodeGenerated(
    Components.Schemas.MatchResultItem.self,
    json: [
      "creator": [
        "id": "00000000-0000-4000-8000-000000000003",
        "name": "Alpha Plays",
        "youtube_channel_id": "alpha",
        "canonical_url": "https://youtube.com/@alpha",
        "favorite": true,
        "contact_available": false,
        "contact": NSNull(),
        "avatar_url": NSNull(),
        "performance_summary": "Strong recent coverage",
        "subscriber_count": 1_000,
        "recent_average_views": 500,
        "recent_median_views": 450,
      ],
      "result_group": "recommended",
      "qualitative_label": "Strong Match",
      "dimension_outcomes": [
        "content_fit": "Strong",
        "audience_fit": "Strong",
        "performance_fit": "Good",
        "promotion_fit": "Strong",
        "brand_safety": "Good",
      ],
      "match_reasons": ["Audience overlap"],
      "match_brief": [
        "content_fit": dimension,
        "audience_fit": dimension,
        "performance_fit": dimension,
        "promotion_fit": dimension,
        "brand_safety": dimension,
        "strengths": ["Audience overlap"],
        "risks": ["Schedule"],
        "evidence": ["Public evidence"],
        "match_reasons": ["Audience overlap"],
      ],
      "outreach": [
        "delivery_id": NSNull(),
        "send_state": "not_sent",
        "response_state": "no_response",
      ],
    ]
  )

  #expect(item.creator.subscriber_count == 1_000)
  #expect(item.outreach.delivery_id == nil)
}

@Test func generatedSMTPSettingsRetainConfiguredAndEmptyOptionals() throws {
  let configured = try decodeGenerated(
    Components.Schemas.SMTPSettingsResponse.self,
    json: [
      "configured": true,
      "host": "smtp.example.com",
      "port": 587,
      "encryption": "starttls",
      "username": "mailer",
      "from_name": "Find Me Gamer",
      "reply_to": "reply@example.com",
      "emails_per_minute": 12,
      "last_test_status": "success",
      "last_tested_at": "2026-09-03T00:00:00Z",
    ]
  )
  let empty = try decodeGenerated(
    Components.Schemas.SMTPSettingsResponse.self,
    json: [
      "configured": false,
      "host": NSNull(),
      "port": NSNull(),
      "encryption": NSNull(),
      "username": NSNull(),
      "from_name": NSNull(),
      "reply_to": NSNull(),
      "emails_per_minute": 10,
      "last_test_status": NSNull(),
      "last_tested_at": NSNull(),
    ]
  )

  #expect(configured.host == "smtp.example.com")
  #expect(configured.port == 587)
  #expect(configured.encryption == .starttls)
  #expect(configured.username == "mailer")
  #expect(configured.from_name == "Find Me Gamer")
  #expect(configured.reply_to == "reply@example.com")
  #expect(configured.last_test_status == .success)
  #expect(configured.last_tested_at != nil)
  #expect(empty.host == nil)
  #expect(empty.port == nil)
  #expect(empty.encryption == nil)
  #expect(empty.username == nil)
  #expect(empty.from_name == nil)
  #expect(empty.reply_to == nil)
  #expect(empty.last_test_status == nil)
  #expect(empty.last_tested_at == nil)
}

@Test func generatedProfilePagesRoundTripNullableCardsAndCursors() throws {
  let creatorPage = try decodeGenerated(
    Components.Schemas.CursorPage_CreatorProfileCard_.self,
    json: [
      "items": [
        [
          "type": "creator",
          "id": "00000000-0000-4000-8000-000000000004",
          "name": "Alpha Plays",
          "youtube_channel_id": "alpha",
          "canonical_url": "https://youtube.com/@alpha",
          "favorite": false,
          "current_facts": [:],
          "brief": [:],
          "source_status": [:],
          "last_analyzed_at": "2026-09-03T00:00:00Z",
          "next_analysis_at": NSNull(),
          "contact": [
            "email": "alpha@example.com",
            "source": "manual",
            "source_url": NSNull(),
            "validation_state": "manual",
          ],
        ]
      ],
      "next_cursor": "creator-next",
    ]
  )
  let gamePage = try decodeGenerated(
    Components.Schemas.CursorPage_GameProfileCard_.self,
    json: [
      "items": [
        [
          "type": "game",
          "id": "00000000-0000-4000-8000-000000000005",
          "name": "Example Game",
          "steam_app_id": "730",
          "canonical_url": "https://store.steampowered.com/app/730",
          "favorite": true,
          "current_facts": [:],
          "brief": [:],
          "source_status": [:],
          "last_analyzed_at": NSNull(),
          "next_analysis_at": "2026-09-04T00:00:00Z",
        ]
      ],
      "next_cursor": NSNull(),
    ]
  )

  let creatorRoundTrip = try roundTripGenerated(creatorPage)
  let gameRoundTrip = try roundTripGenerated(gamePage)
  #expect(creatorRoundTrip.next_cursor == "creator-next")
  #expect(creatorRoundTrip.items[0].contact?.value1.email == "alpha@example.com")
  #expect(creatorRoundTrip.items[0].last_analyzed_at != nil)
  #expect(creatorRoundTrip.items[0].next_analysis_at == nil)
  #expect(gameRoundTrip.next_cursor == nil)
  #expect(gameRoundTrip.items[0].last_analyzed_at == nil)
  #expect(gameRoundTrip.items[0].next_analysis_at != nil)
}

@Test func generatedQueriesAndManualUpdateExposeNullableInputs() throws {
  let query = Operations.listJobs.Input.Query(
    changed_after: "2026-09-03T00:00:00Z",
    status: .running,
    limit: 25
  )
  let update = Components.Schemas.CreatorManualUpdate(
    contact_email: "creator@example.com",
    notes: "Reached at PAX"
  )
  let clearing = Components.Schemas.CreatorManualUpdate(
    contact_email: nil,
    notes: nil
  )

  #expect(query.changed_after == "2026-09-03T00:00:00Z")
  #expect(query.status == .running)
  #expect(update.contact_email == "creator@example.com")
  #expect(update.notes == "Reached at PAX")
  let updateJSON = try encodedJSONObject(update)
  #expect(updateJSON["contact_email"] as? String == "creator@example.com")
  #expect(updateJSON["notes"] as? String == "Reached at PAX")
  #expect(try encodedJSONObject(clearing).isEmpty)
}

@Test func swiftSchemaRecordsAuthoritativeBackendDigest() throws {
  let (backendData, swiftDocument) = try backendDataAndSwiftDocument()
  let recordedDigest = try #require(
    swiftDocument["x-find-me-gamer-source-sha256"] as? String
  )
  let actualDigest = SHA256.hash(data: backendData)
    .map { String(format: "%02x", $0) }
    .joined()

  #expect(recordedDigest == actualDigest)
}

private func decodeGenerated<Value: Decodable>(
  _ type: Value.Type,
  json: Any
) throws -> Value {
  let data = try JSONSerialization.data(withJSONObject: json, options: [.sortedKeys])
  let decoder = JSONDecoder()
  decoder.dateDecodingStrategy = .iso8601
  return try decoder.decode(type, from: data)
}

private func roundTripGenerated<Value: Codable>(_ value: Value) throws -> Value {
  let encoder = JSONEncoder()
  encoder.dateEncodingStrategy = .iso8601
  let data = try encoder.encode(value)
  let decoder = JSONDecoder()
  decoder.dateDecodingStrategy = .iso8601
  return try decoder.decode(Value.self, from: data)
}

private func encodedJSONObject<Value: Encodable>(_ value: Value) throws -> [String: Any] {
  let data = try JSONEncoder().encode(value)
  return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
}

private func backendDataAndSwiftDocument() throws -> (Data, [String: Any]) {
  let testFile = URL(fileURLWithPath: #filePath)
  let repositoryRoot =
    testFile
    .deletingLastPathComponent()
    .deletingLastPathComponent()
    .deletingLastPathComponent()
    .deletingLastPathComponent()
  let backendData = try Data(
    contentsOf: repositoryRoot.appendingPathComponent("backend/openapi.json")
  )
  let swiftData = try Data(
    contentsOf: repositoryRoot.appendingPathComponent(
      "macos/Sources/FindMeGamerAPI/openapi.json"
    )
  )
  let swiftDocument = try #require(
    JSONSerialization.jsonObject(with: swiftData) as? [String: Any]
  )
  return (backendData, swiftDocument)
}
