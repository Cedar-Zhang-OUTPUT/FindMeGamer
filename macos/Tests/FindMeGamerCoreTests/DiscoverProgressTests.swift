import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing

@testable import FindMeGamerCore

@MainActor @Suite struct DiscoverProgressTests {
  @Test func jobEventsUpdateStaleBatchCountsAndSurviveReopen() async throws {
    let api = OpenAPIService(baseURL: URL(string: "https://example.test")!,
      transport: DiscoverProgressTransport(), keyProvider: { "test-key" },
      correlationIDProvider: { "test-correlation" })
    let coordinator = ClientCoordinator(api: api, apiBaseURL: "https://example.test", appVersion: "test")
    await coordinator.discover.open(id: progressID(1))
    #expect(coordinator.discover.batches.first?.analyzingCount == 2)
    await coordinator.consume(.init(
      changes: [.analysis(progressJob(3, status: .succeeded)), .analysis(progressJob(4, status: .failed))],
      affectedProfileIDs: [], affectedMatchTaskIDs: [], affectedGameIDs: [], hasActiveJobs: false))
    #expect(coordinator.discover.batches.first?.succeededCount == 1)
    #expect(coordinator.discover.batches.first?.failedCount == 1)
    await coordinator.discover.open(id: progressID(1))
    #expect(coordinator.discover.batches.first?.succeededCount == 1)
    #expect(coordinator.discover.batches.first?.failedCount == 1)
    coordinator.discover.selectAll()
    #expect(!coordinator.discover.canAddAnalysis)
    coordinator.discover.toggleCandidate(progressID(3))
    #expect(coordinator.discover.canAddAnalysis)
  }

  @Test(.enabled(if: ProcessInfo.processInfo.environment["FMG_DISCOVER_LIVE_READ"] == "1"))
  func liveReadOnlyLibraryAndDiscoverProgressDecode() async throws {
    let key = try #require(ProcessInfo.processInfo.environment["FMG_WORKSPACE_KEY"])
    let api = OpenAPIService(baseURL: URL(string: "https://44.233.174.193")!, keyProvider: { key })
    let coordinator = ClientCoordinator(api: api, apiBaseURL: "https://44.233.174.193", appVersion: "0.4.1")
    await coordinator.library.loadFirstPage()
    #expect(coordinator.library.error == nil)
    #expect(!coordinator.library.items.isEmpty)
    let history = try await api.discoverHistory(cursor: nil)
    var found = false
    for item in history.items {
      let batches = try await api.discoverBatches(id: item.id)
      guard !batches.isEmpty else { continue }
      await coordinator.discover.open(id: item.id)
      var cursor: String?
      repeat {
        let page = try await api.listJobs(changedAfter: cursor, status: nil)
        await coordinator.consume(.init(changes: page.items, affectedProfileIDs: [],
          affectedMatchTaskIDs: [], affectedGameIDs: [], hasActiveJobs: false))
        cursor = page.cursor
        if !page.hasMore { break }
      } while true
      #expect(coordinator.discover.error == nil)
      #expect(coordinator.discover.batches.contains { $0.succeededCount > 0 })
      coordinator.discover.selectAll()
      #expect(!coordinator.discover.canAddAnalysis)
      found = true
    }
    #expect(found)
  }
}

private func progressID(_ n: Int) -> UUID {
  UUID(uuidString: String(format: "10000000-0000-4000-8000-%012d", n))!
}
private func progressJob(_ n: Int, status: JobStatus) -> AnalysisJob {
  .init(id: progressID(n), profileType: .creator, canonicalTargetID: "x:\(n)",
    canonicalURL: "https://x.com/i/user/\(n)", mode: .create, status: status, stage: .finalizing,
    completedUnits: 5, totalUnits: 5, retryable: status == .failed, correlationID: nil,
    profileID: status == .succeeded ? progressID(9) : nil,
    createdAt: Date(timeIntervalSince1970: 1), updatedAt: Date(timeIntervalSince1970: 10),
    startedAt: Date(timeIntervalSince1970: 2), completedAt: Date(timeIntervalSince1970: 10),
    failure: status == .failed ? .init(code: "test_failure", message: "Could not analyze") : nil)
}
private struct DiscoverProgressTransport: ClientTransport {
  func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String) async throws
    -> (HTTPResponse, HTTPBody?) {
    let json: String
    if operationID == "getDiscover" {
      json = #"{"id":"10000000-0000-4000-8000-000000000001","game_name":"Game","status":"done","conditions":{},"candidates":[{"id":"10000000-0000-4000-8000-000000000003","platform":"x","platform_account_id":"3","display_name":"Three","canonical_url":"https://x.com/i/user/3","in_library":false},{"id":"10000000-0000-4000-8000-000000000004","platform":"x","platform_account_id":"4","display_name":"Four","canonical_url":"https://x.com/i/user/4","in_library":false}],"issues":[],"created_at":"2026-09-14T00:00:00Z","updated_at":"2026-09-14T00:00:00Z"}"#
    } else if operationID == "listDiscoverAnalysisBatches" {
      json = #"{"items":[{"id":"10000000-0000-4000-8000-000000000002","discover_id":"10000000-0000-4000-8000-000000000001","mode":"analyze","status":"running","items":[{"candidate_id":"10000000-0000-4000-8000-000000000003","analysis_job_id":"10000000-0000-4000-8000-000000000003","status":"queued","reused":false},{"candidate_id":"10000000-0000-4000-8000-000000000004","analysis_job_id":"10000000-0000-4000-8000-000000000004","status":"queued","reused":false}],"created_at":"2026-09-14T00:00:00Z","updated_at":"2026-09-14T00:00:00Z"}]}"#
    } else { throw APIError.invalidResponse }
    return (HTTPResponse(status: .ok, headerFields: [.contentType: "application/json"]), HTTPBody(json))
  }
}
