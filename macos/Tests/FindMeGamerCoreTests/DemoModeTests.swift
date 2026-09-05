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
    guard case .creator(let creatorProfile) = profile else {
      Issue.record("Expected a Creator demo profile")
      return
    }
    #expect(creatorProfile.contacts.count == 2)
    #expect(creatorProfile.contacts.map(\.purpose) == ["Partnerships", "Press"])
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
    let multi = try #require(
      result.recommendedMatches.first(where: { $0.creator.contacts.count > 1 }))
    let selectedContact = try #require(multi.creator.contacts.last)
    let selections = [
      OutreachRecipientSelection(creatorID: multi.id, email: selectedContact.email)
    ]
    let draft = SendBatchDraft(
      matchTaskID: task.id, creatorIDs: recipientIDs,
      recipientSelections: selections, templateID: template.id)
    let previews = try await service.previewSendBatch(draft)
    #expect(previews.map(\.creatorID) == recipientIDs)
    #expect(previews.allSatisfy { $0.recipientEmail.hasSuffix("@example.test") })

    let batch = try await service.createSendBatch(draft, idempotencyKey: UUID().uuidString)
    #expect(batch.requestedCreatorIDs == recipientIDs)
    #expect(batch.deliveries.count == recipientIDs.count)
    #expect(
      batch.deliveries.first(where: { $0.creatorID == multi.id })?.recipientEmail
        == selectedContact.email)

    let campaigns = try await service.listCampaigns(cursor: nil)
    let campaign = try #require(campaigns.items.first)
    let detail = try await service.campaign(id: campaign.id)
    #expect(!detail.sendBatches.isEmpty)

    #expect(try await service.smtpSettings().configured)
    #expect(try await service.connection(.deepSeek).configured)
    #expect(try await service.sharedSettings().creatorIntervalDays <= 30)
  }

  @Test func demoOutreachRejectsMissingDuplicateAndInactiveEmailSelections() async throws {
    let service = DemoAPIService()
    let task = try #require(try await service.listMatches(cursor: nil).items.first)
    let result = try await service.match(id: task.id)
    let creator = try #require(
      result.recommendedMatches.first(where: { $0.creator.contacts.count > 1 }))

    do {
      _ = try await service.previewSendBatch(
        SendBatchDraft(matchTaskID: task.id, creatorIDs: [creator.id]))
      Issue.record("Multiple active emails must require an explicit selection")
    } catch let error as APIError {
      #expect(error.code == "recipient_email_selection_required")
    }

    do {
      _ = try await service.previewSendBatch(
        SendBatchDraft(
          matchTaskID: task.id, creatorIDs: [creator.id],
          recipientSelections: [
            OutreachRecipientSelection(creatorID: creator.id, email: "inactive@example.test")
          ]))
      Issue.record("An inactive email must be rejected")
    } catch let error as APIError {
      #expect(error.code == "recipient_email_selection_invalid")
    }

    do {
      _ = try await service.previewSendBatch(
        SendBatchDraft(
          matchTaskID: task.id, creatorIDs: [creator.id],
          recipientSelections: [
            OutreachRecipientSelection(
              creatorID: creator.id, email: creator.creator.contacts[0].email),
            OutreachRecipientSelection(
              creatorID: creator.id, email: creator.creator.contacts[1].email),
          ]))
      Issue.record("A Creator cannot receive more than one selected address")
    } catch let error as APIError {
      #expect(error.code == "recipient_email_selection_invalid")
    }
  }

  @Test func demoOutreachRejectsInvalidCreatorIDsBeforeRenderingOrSending() async throws {
    let service = DemoAPIService()
    let task = try #require(try await service.listMatches(cursor: nil).items.first)
    let result = try await service.match(id: task.id)
    let creator = try #require(result.recommendedMatches.first?.creator)

    for creatorIDs in [[], [creator.id, creator.id]] {
      let draft = SendBatchDraft(matchTaskID: task.id, creatorIDs: creatorIDs)

      do {
        _ = try await service.previewSendBatch(draft)
        Issue.record("Creator IDs must be non-empty and unique")
      } catch let error as APIError {
        #expect(error.code == "request_invalid")
      }

      do {
        _ = try await service.createSendBatch(draft, idempotencyKey: UUID().uuidString)
        Issue.record("An invalid request must not create duplicate deliveries")
      } catch let error as APIError {
        #expect(error.code == "request_invalid")
      }
    }

    do {
      _ = try await service.previewSendBatch(
        SendBatchDraft(matchTaskID: task.id, creatorIDs: [UUID()]))
      Issue.record("Every requested Creator must belong to the Match result")
    } catch let error as APIError {
      #expect(error.code == "creator_not_in_match")
    }
  }

  @Test func demoManualEmailAddChangeAndClearPreserveDiscoveredContacts() async throws {
    let service = DemoAPIService()
    let page = try await service.listProfiles(
      type: .creator, query: "tactical", onlyCollection: false, cursor: nil, limit: 10)
    let creatorID = try #require(page.items.first?.id)

    let added = try await service.updateCreatorManual(
      id: creatorID, email: "  manual@example.test  ", notes: "First note")
    #expect(added.contact?.email == "manual@example.test")
    #expect(
      added.contacts.map(\.email) == [
        "manual@example.test",
        "tactical.cedar@example.test",
        "tacticalcedar.press@example.test",
      ])
    #expect(added.contacts.dropFirst().map(\.purpose) == ["Partnerships", "Press"])

    let changed = try await service.updateCreatorManual(
      id: creatorID, email: "new-manual@example.test", notes: "Changed note")
    #expect(
      changed.contacts.map(\.email) == [
        "new-manual@example.test",
        "tactical.cedar@example.test",
        "tacticalcedar.press@example.test",
      ])
    #expect(changed.contacts.filter { $0.availability == .manual }.count == 1)

    let cleared = try await service.updateCreatorManual(
      id: creatorID, email: nil, notes: "Cleared")
    #expect(cleared.contact?.email == "tactical.cedar@example.test")
    #expect(
      cleared.contacts.map(\.email) == [
        "tactical.cedar@example.test",
        "tacticalcedar.press@example.test",
      ])
    #expect(cleared.contacts.allSatisfy { $0.availability == .discovered })

    let shadowed = try await service.updateCreatorManual(
      id: creatorID, email: "TACTICAL.CEDAR@example.test", notes: "Same address")
    #expect(
      shadowed.contacts.map(\.email) == [
        "TACTICAL.CEDAR@example.test",
        "tacticalcedar.press@example.test",
      ])
    #expect(shadowed.contacts.first?.availability == .manual)
    let matchID = try #require(try await service.listMatches(cursor: nil).items.first?.id)
    let shadowedMatch = try await service.match(id: matchID)
    let shadowedCandidate = try #require(
      (shadowedMatch.recommendedMatches + shadowedMatch.otherMatches).first {
        $0.id == creatorID
      })
    #expect(shadowedCandidate.creator.contacts.map(\.email) == shadowed.contacts.map(\.email))

    let restored = try await service.updateCreatorManual(
      id: creatorID, email: nil, notes: "Restored")
    #expect(
      restored.contacts.map(\.email) == [
        "tactical.cedar@example.test",
        "tacticalcedar.press@example.test",
      ])
    #expect(restored.contacts.map(\.purpose) == ["Partnerships", "Press"])
    #expect(restored.contact?.source == "channel_about")
    let restoredMatch = try await service.match(id: matchID)
    let restoredCandidate = try #require(
      (restoredMatch.recommendedMatches + restoredMatch.otherMatches).first {
        $0.id == creatorID
      })
    #expect(restoredCandidate.creator.contacts.map(\.email) == restored.contacts.map(\.email))

    let refreshedPage = try await service.listProfiles(
      type: .creator, query: "tactical", onlyCollection: false, cursor: nil, limit: 10)
    guard case .creator(let refreshedCard) = try #require(refreshedPage.items.first) else {
      Issue.record("Expected a Creator card")
      return
    }
    #expect(refreshedCard.contacts == restored.contacts)
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
