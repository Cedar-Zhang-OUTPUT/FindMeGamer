import Foundation
import Testing

@testable import FindMeGamerCore

@Suite struct DemoScenarioTests {
  @Test func runtimeScenariosAreExplicitAndUnknownValuesStayNormal() {
    #expect(DemoScenario(environment: [:]) == .normal)
    #expect(DemoScenario(environment: ["FMG_DEMO_SCENARIO": "unknown"]) == .normal)
    #expect(DemoScenario(environment: ["FMG_DEMO_SCENARIO": "qa-journey"]) == .qaJourney)
    #expect(DemoScenario(environment: ["FMG_DEMO_SCENARIO": "empty-library"]) == .emptyLibrary)
  }

  @Test func normalDemoStillCompletesMatchImmediately() async throws {
    let service = DemoAPIService()
    let gameID = try #require(
      try await service.listProfiles(
        type: .game, query: "", onlyCollection: false, cursor: nil, limit: 10
      ).items.first?.id)
    let task = try await service.createMatch(gameID: gameID, idempotencyKey: UUID().uuidString)
    #expect(task.status == .succeeded)
    #expect(try await service.match(id: task.id).state == .available)
  }

  @Test func qaMatchAdvancesThroughPollingWithoutInventingPendingProgress() async throws {
    let service = DemoAPIService(scenario: .qaJourney)
    let gameID = try #require(
      try await service.listProfiles(
        type: .game, query: "", onlyCollection: false, cursor: nil, limit: 10
      ).items.first?.id)
    let task = try await service.createMatch(gameID: gameID, idempotencyKey: UUID().uuidString)
    #expect(task.status == .queued)
    #expect(task.totalUnits == 0)
    #expect(task.completedUnits == 0)
    #expect(try await service.match(id: task.id).recommendedMatches.isEmpty)

    var cursor: String?
    var statuses: [JobStatus] = []
    var stages: [MatchStage] = []
    var previousUpdate = task.updatedAt
    for _ in 0..<4 {
      let page = try await service.listJobs(changedAfter: cursor, status: nil)
      cursor = page.cursor
      let changes = page.items.compactMap { change -> ChangedMatchJob? in
        guard case .match(let match) = change, match.id == task.id else { return nil }
        return match
      }
      let change = try #require(changes.first)
      #expect(changes.count == 1)
      #expect(change.updatedAt > previousUpdate)
      previousUpdate = change.updatedAt
      statuses.append(change.status)
      stages.append(change.stage)
      if change.status != .succeeded {
        #expect(change.totalUnits == 0)
        #expect(change.completedUnits == 0)
        #expect(change.resultCount == 0)
      }
    }
    #expect(statuses == [.queued, .running, .running, .succeeded])
    #expect(stages == [.screening, .screening, .pairwise, .ranking])
    let completed = try await service.match(id: task.id)
    #expect(completed.state == .available)
    #expect(!completed.recommendedMatches.isEmpty)
    #expect(
      completed.resultCount == completed.recommendedMatches.count + completed.otherMatches.count)
    let later = try await service.listJobs(changedAfter: cursor, status: nil)
    let final = later.items.compactMap { change -> ChangedMatchJob? in
      guard case .match(let match) = change, match.id == task.id else { return nil }
      return match
    }.first
    #expect(final?.status == .succeeded)
    #expect(final?.updatedAt == completed.updatedAt)
  }

  @Test func qaPreviewFailsOnlyTheFirstValidRequestAndRetryKeepsTheSameRecipient() async throws {
    let service = DemoAPIService(scenario: .qaJourney)
    let task = try #require(try await service.listMatches(cursor: nil).items.first)
    let result = try await service.match(id: task.id)
    let candidate = try #require(result.recommendedMatches.first { $0.creator.contacts.count == 1 })
    do {
      _ = try await service.previewSendBatch(SendBatchDraft(matchTaskID: task.id, creatorIDs: []))
      Issue.record("Invalid requests must remain invalid without consuming the scenario failure")
    } catch let error as APIError {
      #expect(error.code == "request_invalid")
    }
    let draft = SendBatchDraft(matchTaskID: task.id, creatorIDs: [candidate.id])
    do {
      _ = try await service.previewSendBatch(draft)
      Issue.record("The first valid preview should expose the recoverable Demo failure")
    } catch let error as APIError {
      #expect(error.code == "demo_preview_retry")
      #expect(error.retryable)
    }
    let previews = try await service.previewSendBatch(draft)
    #expect(previews.map(\.creatorID) == [candidate.id])
    #expect(previews.first?.recipientEmail == candidate.creator.contacts.first?.email)
    let batch = try await service.createSendBatch(draft, idempotencyKey: UUID().uuidString)
    #expect(batch.requestedCreatorIDs == [candidate.id])
  }

  @Test func emptyLibraryCanBePopulatedThroughTheExistingAnalyzeFlow() async throws {
    let service = DemoAPIService(scenario: .emptyLibrary)
    #expect(
      try await service.listProfiles(
        type: .game, query: "", onlyCollection: false, cursor: nil, limit: 10
      ).items.isEmpty)
    #expect(
      try await service.listProfiles(
        type: .creator, query: "", onlyCollection: false, cursor: nil, limit: 10
      ).items.isEmpty)
    #expect(try await service.listMatches(cursor: nil).items.isEmpty)
    #expect(try await service.listCampaigns(cursor: nil).items.isEmpty)
    _ = try await service.createAnalysisJob(
      AnalysisRequest(url: "https://store.steampowered.com/app/730/", profileType: .game),
      idempotencyKey: UUID().uuidString)
    #expect(
      try await service.listProfiles(
        type: .game, query: "", onlyCollection: false, cursor: nil, limit: 10
      ).items.count == 1)
  }
}
