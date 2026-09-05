import Foundation
import Testing

@testable import FindMeGamerCore

@Suite @MainActor struct OutreachNavigationTests {
  @Test func campaignSelectionUsesTheExactIDAndReplacesThePreviousDetail() {
    let navigation = WorkspaceNavigationState()
    let first = UUID()
    let second = UUID()

    #expect(navigation.outreachCampaign == nil)
    navigation.openCampaign(id: first)
    #expect(navigation.outreachCampaign == OutreachCampaignDestination(id: first))
    navigation.openCampaign(id: first)
    #expect(navigation.outreachCampaign?.id == first)
    navigation.openCampaign(id: second)
    #expect(navigation.outreachCampaign?.id == second)
  }

  @Test func nativeBackCanClearTheDestinationAndTheSameCampaignCanReopen() {
    let navigation = WorkspaceNavigationState()
    let id = UUID()
    navigation.openCampaign(id: id)
    // navigationDestination(item:) writes nil when the user navigates back.
    navigation.outreachCampaign = nil
    #expect(navigation.outreachCampaign == nil)
    navigation.openCampaign(id: id)
    #expect(navigation.outreachCampaign?.id == id)
  }

  @Test func openingCampaignDoesNotRewriteOtherWorkspaceHistory() {
    let navigation = WorkspaceNavigationState()
    navigation.libraryPath.append("library")
    navigation.matchPath.append("match")
    navigation.settingsPath.append("settings")
    navigation.openCampaign(id: UUID())
    #expect(navigation.libraryPath.count == 1)
    #expect(navigation.matchPath.count == 1)
    #expect(navigation.settingsPath.count == 1)
  }
}
