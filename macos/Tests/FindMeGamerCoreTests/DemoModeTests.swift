import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct DemoModeTests {
  @Test func demoServiceProvidesSearchableInteractiveProfiles() async throws {
    let service = DemoAPIService()

    let workspace = try await service.validateSession()
    #expect(workspace.workspaceName == "Find Me Gamer Demo")

    let games = try await service.listProfiles(
      type: .game, query: "", onlyCollection: false, cursor: nil, limit: 100)
    let creators = try await service.listProfiles(
      type: .creator, query: "", onlyCollection: false, cursor: nil, limit: 100)
    #expect(games.items.count >= 3)
    #expect(creators.items.count >= 6)

    let searched = try await service.listProfiles(
      type: .creator, query: "tactical", onlyCollection: false, cursor: nil, limit: 100)
    let creator = try #require(searched.items.first)
    guard case .creator(let creatorCard) = creator else {
      Issue.record("Expected a Creator demo card")
      return
    }

    _ = try await service.setFavorite(type: .creator, id: creatorCard.id, favorite: true)
    let favorites = try await service.listProfiles(
      type: .creator, query: "tactical", onlyCollection: true, cursor: nil, limit: 100)
    #expect(favorites.items.map(\.id) == [creatorCard.id])

    let profile = try await service.profile(type: .creator, id: creatorCard.id)
    #expect(profile.id == creatorCard.id)
  }

  @Test func demoServiceProvidesMatchOutreachAndSettingsStories() async throws {
    let service = DemoAPIService()
    let history = try await service.listMatches(cursor: nil)
    let task = try #require(history.items.first)
    let result = try await service.match(id: task.id)
    #expect(result.status == .succeeded)
    #expect(result.recommendedMatches.count >= 2)
    #expect(!result.otherMatches.isEmpty)

    let templates = try await service.listTemplates()
    let template = try #require(templates.first(where: { $0.isDefault }))
    do {
      try await service.deleteTemplate(id: template.id)
      Issue.record("The local demo must preserve the default Template invariant")
    } catch let error as APIError {
      #expect(error.code == "template_default_delete_forbidden")
    }
    let recipientIDs = Array(result.recommendedMatches.prefix(2).map(\.id))
    let draft = SendBatchDraft(
      matchTaskID: task.id, creatorIDs: recipientIDs, templateID: template.id)
    let previews = try await service.previewSendBatch(draft)
    #expect(previews.map(\.creatorID) == recipientIDs)
    #expect(previews.allSatisfy { $0.recipientEmail.hasSuffix("@example.test") })

    let batch = try await service.createSendBatch(draft, idempotencyKey: UUID().uuidString)
    #expect(batch.requestedCreatorIDs == recipientIDs)
    #expect(batch.deliveries.count == recipientIDs.count)

    let campaigns = try await service.listCampaigns(cursor: nil)
    let campaign = try #require(campaigns.items.first)
    let detail = try await service.campaign(id: campaign.id)
    #expect(!detail.sendBatches.isEmpty)

    #expect(try await service.smtpSettings().configured)
    #expect(try await service.connection(.deepSeek).configured)
    #expect(try await service.sharedSettings().creatorIntervalDays <= 30)
  }

  @MainActor
  @Test func demoSessionAuthenticatesWithoutKeychainOrNetwork() async {
    let session = AppSession.demo()
    await session.restore()

    #expect(session.state == .authenticated)
    #expect(session.workspaceSession?.workspaceName == "Find Me Gamer Demo")
    #expect(session.service != nil)
  }
}
