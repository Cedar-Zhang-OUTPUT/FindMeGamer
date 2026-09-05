import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct DemoOutreachMatchSyncTests {
  @Test func acceptedDemoBatchRefreshesOnlyItsMatchAndSelectedCreator() async throws {
    let service = DemoAPIService()
    let history = try await service.listMatches(cursor: nil)
    let task = try #require(history.items.first)
    let before = try await service.match(id: task.id)
    let candidate = try #require(
      before.recommendedMatches.first {
        $0.creator.contacts.count > 1 && MatchOutreachActionPolicy.isEligibleForNewSend($0)
      })
    let email = try #require(candidate.creator.contacts.last?.email)
    let otherTask = try #require(history.items.first { $0.id != task.id })
    let otherBefore = try await service.match(id: otherTask.id)
    var selection = MatchRecipientSelection()
    selection.toggle(candidate)

    let draft = SendBatchDraft(
      matchTaskID: task.id, creatorIDs: [candidate.id],
      recipientSelections: [OutreachRecipientSelection(creatorID: candidate.id, email: email)])
    _ = try await service.previewSendBatch(draft)
    let batch = try await service.createSendBatch(draft, idempotencyKey: UUID().uuidString)
    let delivery = try #require(batch.deliveries.first)
    #expect(delivery.recipientEmail == email)

    let refreshed = try await service.match(id: task.id)
    let sent = try #require(refreshed.recommendedMatches.first { $0.id == candidate.id })
    #expect(sent.outreach.deliveryID == delivery.id)
    #expect(sent.outreach.sendState == .sent)
    #expect(sent.outreach.responseState == .pending)
    #expect(!MatchOutreachActionPolicy.isEligibleForNewSend(sent))
    #expect(sent.creator.contacts == candidate.creator.contacts)
    selection.reconcile(with: refreshed)
    #expect(selection.isEmpty)

    let unchangedBefore = (before.recommendedMatches + before.otherMatches).filter {
      $0.id != candidate.id
    }
    let unchangedAfter = (refreshed.recommendedMatches + refreshed.otherMatches).filter {
      $0.id != candidate.id
    }
    #expect(unchangedAfter == unchangedBefore)
    #expect(try await service.match(id: otherTask.id) == otherBefore)
  }
}
