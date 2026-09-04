import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct ModernWorkspacePresentationTests {
  @Test func workspaceUsesOneEditorialIntentPerDestination() {
    #expect(WorkspacePageCopy.library.title == "Profiles worth knowing.")
    #expect(WorkspacePageCopy.match.title == "Find the signal in the noise.")
    #expect(WorkspacePageCopy.outreach.title == "Conversations in motion.")
    #expect(WorkspacePageCopy.settings.title == "Shape your workspace.")
    #expect(Set(WorkspacePageCopy.all.map(\.title)).count == WorkspacePageCopy.all.count)
  }

  @Test func everySidebarDestinationHasOneDistinctCustomGlyph() {
    let glyphs = AppDestination.allCases.map(SidebarGlyph.init(destination:))
    #expect(glyphs == [.libraryMatrix, .matchOrbit, .outreachSignal, .settingsControls])
    #expect(Set(glyphs).count == AppDestination.allCases.count)
  }

  @Test func sidebarGlyphContrastFollowsWindowFocus() {
    #expect(
      SidebarGlyphContrastPolicy.mode(isSelected: true, isControlActive: true)
        == .activeSelection)
    #expect(
      SidebarGlyphContrastPolicy.mode(isSelected: true, isControlActive: false)
        == .inactiveSelection)
    #expect(
      SidebarGlyphContrastPolicy.mode(isSelected: false, isControlActive: false) == .unselected)
  }

  @Test func visualSystemKeepsAQuietFourStepRhythm() {
    #expect(WorkspaceDesign.spaceXS == 6)
    #expect(WorkspaceDesign.spaceS == 10)
    #expect(WorkspaceDesign.spaceM == 16)
    #expect(WorkspaceDesign.spaceL == 24)
    #expect(WorkspaceDesign.cardCornerRadius == 16)
    #expect(WorkspaceDesign.featureCornerRadius == 22)
    #expect(WorkspaceDesign.libraryGridMinimumWidth == 240)
  }

  @Test func candidatePreviewShowsOneReasonBeforeProgressiveDisclosure() {
    let policy = MatchCandidatePreviewPolicy(reasons: [
      "First signal", "Second signal", "Third signal",
    ])
    #expect(policy.primaryReason == "First signal")
    #expect(policy.additionalReasonCount == 2)

    let empty = MatchCandidatePreviewPolicy(reasons: [])
    #expect(empty.primaryReason == nil)
    #expect(empty.additionalReasonCount == 0)
  }

  @Test func campaignMetricsPreserveEveryFieldButPrioritizeDecisionSignals() {
    let metrics = CampaignMetrics(
      sentCreators: 8,
      accepted: 3,
      declined: 1,
      noResponse: 3,
      failed: 1,
      responseRate: 0.5)

    let items = CampaignMetricPresentation.items(metrics)
    #expect(
      items.map(\.label) == [
        "Sent", "Response Rate", "Accepted", "Declined", "No Response", "Failed",
      ])
    #expect(items.filter(\.isPrimary).map(\.label) == ["Sent", "Response Rate", "Accepted"])
    #expect(
      items.map(\.systemImage) == [
        "paperplane.fill", "arrowshape.turn.up.left.fill", "checkmark.circle.fill",
        "xmark.circle.fill", "clock.fill", "exclamationmark.triangle.fill",
      ])
  }
}
