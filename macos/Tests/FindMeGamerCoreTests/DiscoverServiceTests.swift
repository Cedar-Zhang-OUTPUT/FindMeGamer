import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing

@testable import FindMeGamerCore

@Suite struct DiscoverServiceTests {
  @Test func failedDiscoveryRetryUsesOriginalRecord() async throws {
    let transport = DiscoverTransport()
    let api = OpenAPIService(
      baseURL: URL(string: "https://example.test")!, transport: transport,
      keyProvider: { "test-key" }, correlationIDProvider: { "test-correlation" })
    let id = UUID(uuidString: "10000000-0000-4000-8000-000000000001")!
    let record = try await api.retryDiscover(id: id)
    #expect(record.id == id)
    #expect(record.status == "running")
    #expect(
      await transport.request?.path?.lowercased()
        == "/api/v1/discover/10000000-0000-4000-8000-000000000001/retry")
  }
  @Test func generatedBatchRequestPreservesExplicitModeCandidatesAuthAndReusedFlag() async throws {
    let transport = DiscoverTransport()
    let api = OpenAPIService(
      baseURL: URL(string: "https://example.test")!, transport: transport,
      keyProvider: { "test-key" }, correlationIDProvider: { "test-correlation" })
    let id = UUID(uuidString: "10000000-0000-4000-8000-000000000001")!
    let result = try await api.createDiscoverBatch(
      id: id, candidateIDs: [id], mode: .analyzeAndMatch, idempotencyKey: "same-request")
    #expect(result.reusedCount == 1)
    #expect(result.succeededCount == 0)
    #expect(result.matchID == id)
    let body = try JSONSerialization.jsonObject(with: await transport.body) as! [String: Any]
    #expect(body["mode"] as? String == "analyze_and_match")
    #expect(body["candidate_ids"] as? [String] == [id.uuidString])
    let request = try #require(await transport.request)
    #expect(request.headerFields[.authorization] == "Bearer test-key")
    #expect(request.headerFields[HTTPField.Name("Idempotency-Key")!] == "same-request")
    #expect(
      request.path?.lowercased()
        == "/api/v1/discover/10000000-0000-4000-8000-000000000001/analysis-batches")
  }
  @Test func nullableYouTubeIdentityMapsRealXAccount() async throws {
    let api = OpenAPIService(
      baseURL: URL(string: "https://example.test")!, transport: DiscoverTransport(),
      keyProvider: { "test-key" }, correlationIDProvider: { "test-correlation" })
    guard case .creator(let profile) = try await api.profile(type: .creator, id: UUID()) else {
      Issue.record("Expected creator")
      return
    }
    #expect(profile.youtubeChannelID == nil)
    #expect(profile.platformAccountID == "98765")
    #expect(profile.currentFacts["follower_count"] == .integer(1234))
  }
}

private actor DiscoverTransport: ClientTransport {
  var request: HTTPRequest?
  var body = Data()
  func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String) async throws
    -> (HTTPResponse, HTTPBody?)
  {
    self.request = request
    if let body { self.body = try await Data(collecting: body, upTo: 100_000) }
    let json: String
    let status: HTTPResponse.Status
    if operationID == "retryDiscover" {
      status = .accepted
      json =
        #"{"id":"10000000-0000-4000-8000-000000000001","game_name":"Demo","status":"running","stage":"finding_creators","conditions":{},"candidates":[],"issues":[],"created_at":"2026-09-14T00:00:00Z","updated_at":"2026-09-14T00:00:00Z"}"#
    } else if operationID == "createDiscoverAnalysisBatch" {
      status = .accepted
      json =
        #"{"id":"10000000-0000-4000-8000-000000000001","discover_id":"10000000-0000-4000-8000-000000000001","mode":"analyze_and_match","status":"done","items":[{"candidate_id":"10000000-0000-4000-8000-000000000001","status":"succeeded","reused":true}],"match_task_id":"10000000-0000-4000-8000-000000000001","created_at":"2026-09-14T00:00:00Z","updated_at":"2026-09-14T00:00:00Z"}"#
    } else {
      status = .ok
      json =
        #"{"type":"creator","id":"10000000-0000-4000-8000-000000000001","name":"Indie X","platform":"x","platform_account_id":"98765","youtube_channel_id":null,"canonical_url":"https://x.com/indiex","favorite":false,"current_facts":{"follower_count":1234,"post_count":45},"brief":{},"source_status":{},"last_analyzed_at":null,"next_analysis_at":null,"contact":null,"analysis":{},"model_metadata":{},"prompt_metadata":{},"manual_notes":null}"#
    }
    return (
      HTTPResponse(status: status, headerFields: [.contentType: "application/json"]), HTTPBody(json)
    )
  }
}
