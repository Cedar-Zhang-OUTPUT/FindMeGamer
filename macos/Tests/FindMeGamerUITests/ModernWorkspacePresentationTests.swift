import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct ModernWorkspacePresentationTests {
  @Test func workspaceHeadersIdentifyTheDestinationWithoutInstructionalSubtitles() {
    #expect(WorkspacePageCopy.all.map(\.id) == AppDestination.allCases.map(\.rawValue))
    #expect(
      WorkspacePageCopy.all.map(\.title) == [
        "Discover", "Match", "Outreach", "Library", "Settings",
      ])
    #expect(Set(WorkspacePageCopy.all.map(\.title)).count == WorkspacePageCopy.all.count)
  }

  @Test func everySidebarDestinationHasOneDistinctCustomGlyph() {
    let glyphs = AppDestination.allCases.map(SidebarGlyph.init(destination:))
    #expect(
      glyphs == [.discoverSearch, .matchOrbit, .outreachSignal, .libraryMatrix, .settingsControls])
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

  @Test func analyzeInspectorIsPresentedOnlyInsideTheLibraryWorkspace() {
    #expect(
      WorkspaceInspectorPolicy.isPresented(requested: true, destination: .library))
    #expect(
      !WorkspaceInspectorPolicy.isPresented(requested: true, destination: .match))
    #expect(
      !WorkspaceInspectorPolicy.isPresented(requested: true, destination: .outreach))
    #expect(
      !WorkspaceInspectorPolicy.isPresented(requested: true, destination: .settings))
    #expect(
      !WorkspaceInspectorPolicy.isPresented(requested: false, destination: .library))
  }

  @Test func templateWorkspaceAdaptsInsideTheOuterSidebarDetailColumn() {
    #expect(
      TemplateWorkspaceLayoutPolicy.layout(for: 879) == .compact)
    #expect(
      TemplateWorkspaceLayoutPolicy.layout(for: 880) == .columns(selectorWidth: 220))
    #expect(
      TemplateWorkspaceLayoutPolicy.layout(for: 1_200) == .columns(selectorWidth: 288))
    #expect(
      TemplateWorkspaceLayoutPolicy.layout(for: 2_000) == .columns(selectorWidth: 320))
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
