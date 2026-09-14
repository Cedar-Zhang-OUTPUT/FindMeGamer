import Foundation
import Testing

@testable import FindMeGamerCore

/// Opt-in real OpenAPI HTTP/DB/worker acceptance; upstreams and broker are simulated.
@MainActor @Suite struct NativeDiscoverHTTPAcceptanceTests {
  private func step(_ phase: String) async throws -> [String: Any] {
    var request = URLRequest(url: URL(string: "http://127.0.0.1:18765/fixture/step/\(phase)")!)
    request.httpMethod = "POST"
    request.setValue("Bearer test-workspace-access-key", forHTTPHeaderField: "Authorization")
    let (data, response) = try await URLSession.shared.data(for: request)
    #expect((response as? HTTPURLResponse)?.statusCode == 200)
    return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
  }

  @Test(.enabled(if: ProcessInfo.processInfo.environment["FMG_DISCOVER_HTTP_RESUME"] == "1"))
  func persistedSuccessSurvivesServerProcessRestartAndDuplicateWorkers() async throws {
    let api = OpenAPIService(baseURL: URL(string: "http://127.0.0.1:18765")!,
                             keyProvider: { "test-workspace-access-key" })
    let before = try await step("observe")
    let history = try await api.discoverHistory(cursor: nil)
    let recordID = try #require(history.items.first?.id)
    let batch = try #require(try await api.discoverBatches(id: recordID).first)
    #expect(batch.status == "partial")
    _ = try await step("discover")
    _ = try await step("analysis")
    _ = try await step("batch")
    _ = try await step("match")
    let after = try await step("observe")
    for key in ["analysis_count", "creator_count", "match_count", "locked_count"] {
      #expect(before[key] as? Int == after[key] as? Int)
    }
    #expect(after["manual_preserved"] as? Bool == true)
    #expect(after["match_done"] as? Bool == true)
    #expect(try await api.discoverBatches(id: recordID).first?.matchID == batch.matchID)
    let xID = try #require((after["x_profile_id"] as? String).flatMap(UUID.init(uuidString:)))
    let document = try await api.profileEdit(type: .creator, id: xID)
    #expect(document.fields.first { $0.key == "facts.title" }?.value == .text("Accepted X title"))
  }

  @Test(.enabled(if: ProcessInfo.processInfo.environment["FMG_DISCOVER_HTTP_ACCEPTANCE"] == "1"))
  func newSteamDiscoverSubsetWorkersReopenAndWholeLibraryMatch() async throws {
    let api = OpenAPIService(baseURL: URL(string: "http://127.0.0.1:18765")!,
                             keyProvider: { "test-workspace-access-key" })
    _ = try await api.validateSession()
    let capabilities = try await api.discoverCapabilities()
    #expect(capabilities.filter { ["twitch", "instagram"].contains($0.platform) }
      .allSatisfy { !$0.available && $0.reason != nil })
    let baseline = try await step("observe")
    let game = try await api.resolveDiscoverGame(url: "https://store.steampowered.com/app/1245620")
    #expect(!game.name.isEmpty)
    #expect(game.id == nil)
    #expect(try await step("observe")["analysis_count"] as? Int == baseline["analysis_count"] as? Int)
    var conditions = DiscoverConditions()
    conditions.platforms = ["youtube", "x"]
    let key = UUID().uuidString
    let record = try await api.createDiscover(game: game, conditions: conditions, idempotencyKey: key)
    #expect(try await api.createDiscover(game: game, conditions: conditions, idempotencyKey: key).id == record.id)
    _ = try await step("discover")
    let waiting = try await api.discover(id: record.id)
    #expect(waiting.stage == "preparing_game")
    #expect(waiting.candidates.isEmpty)
    _ = try await step("analysis")
    _ = try await step("discover")
    let found = try await api.discover(id: record.id)
    #expect(found.status == "done")
    #expect(found.candidates.count == 5)
    #expect(try await step("observe")["creator_count"] as? Int == baseline["creator_count"] as? Int)
    let model = DiscoverModel(api: api)
    await model.open(id: record.id)
    model.selectAll()
    model.deselectAll()
    for candidate in found.candidates where candidate.name != "Unselected" {
      model.toggleCandidate(candidate.id)
    }
    model.presentAnalysisConfirmation()
    model.cancelAnalysisConfirmation()
    #expect(try await api.discoverBatches(id: record.id).isEmpty)
    let selected = Array(model.selectedIDs)
    #expect(selected.count == 4)
    let batchKey = UUID().uuidString
    let batch = try await api.createDiscoverBatch(id: record.id, candidateIDs: selected,
      mode: .analyzeAndMatch, idempotencyKey: batchKey)
    #expect(try await api.createDiscoverBatch(id: record.id, candidateIDs: selected,
      mode: .analyzeAndMatch, idempotencyKey: batchKey).id == batch.id)
    _ = try await step("join")
    _ = try await step("batch")
    let underway = try #require(try await api.discoverBatches(id: record.id).first)
    #expect(underway.reusedCount == 1)
    _ = try await step("analysis")
    _ = try await step("batch")
    _ = try await step("match")
    // New presentation object models closure/reopen; server work is already durable.
    let reopened = DiscoverModel(api: api)
    await reopened.open(id: record.id)
    let completed = try #require(reopened.batches.first)
    #expect(completed.status == "partial")
    #expect(completed.failedCount == 1)
    #expect(completed.succeededCount == 2)
    #expect(completed.reusedCount == 1)
    let matchID = try #require(completed.matchID)
    _ = try await api.match(id: matchID)
    _ = try await step("batch")
    _ = try await step("match")
    let evidence = try await step("observe")
    #expect(evidence["match_count"] as? Int == 1)
    #expect(evidence["locked_count"] as? Int == 4)
    #expect(evidence["old_creator_matched"] as? Bool == true)
    #expect(evidence["fact_only_excluded"] as? Bool == true)
    #expect(evidence["joined_job_preserved"] as? Bool == true)
    #expect(evidence["unselected_absent"] as? Bool == true)
    #expect(evidence["match_done"] as? Bool == true)
    #expect(evidence["smtp_count"] as? Int == 0)
    let xID = try #require((evidence["x_profile_id"] as? String).flatMap(UUID.init(uuidString:)))
    _ = try await api.profile(type: .creator, id: xID)
    let editor = try await api.profileEdit(type: .creator, id: xID)
    let saved = try await api.saveProfileEdit(type: .creator, id: xID,
      patch: .init(expectedRevision: editor.revision, changes: ["facts.title": .text("Accepted X title")], resetFields: []))
    #expect(saved.fields.first { $0.key == "facts.title" }?.value == .text("Accepted X title"))
    let contact = try await api.updateCreatorManual(id: xID, email: "native-x@example.com", notes: "HTTP acceptance")
    #expect(contact.contact?.email == "native-x@example.com")
    #expect(try await api.discoverHistory(cursor: nil).items.first?.candidateCount == 5)
  }
}
