import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct WorkspaceMotionTests {
  @Test func orderedSelectionsResolveStableTransitionDirections() {
    #expect(
      WorkspaceMotionPolicy.direction(
        from: AppDestination.library,
        to: .outreach,
        ordered: AppDestination.allCases) == .forward)
    #expect(
      WorkspaceMotionPolicy.direction(
        from: AppDestination.settings,
        to: .match,
        ordered: AppDestination.allCases) == .backward)
    #expect(
      WorkspaceMotionPolicy.direction(
        from: AppDestination.match,
        to: .match,
        ordered: AppDestination.allCases) == .stationary)
  }

  @Test func standardMotionUsesBriefLowDisplacementProfiles() {
    #expect(
      WorkspaceMotionPolicy.profile(for: .destination, reduceMotion: false)
        == WorkspaceMotionProfile(duration: 0.22, displacement: 10, inactiveScale: 1))
    #expect(
      WorkspaceMotionPolicy.profile(for: .switcher, reduceMotion: false)
        == WorkspaceMotionProfile(duration: 0.18, displacement: 8, inactiveScale: 1))
    #expect(
      WorkspaceMotionPolicy.profile(for: .selectionFeedback, reduceMotion: false)
        == WorkspaceMotionProfile(duration: 0.16, displacement: 0, inactiveScale: 0.94))
  }

  @Test func reduceMotionRemovesSpatialMovementAndScaling() {
    for role in WorkspaceMotionRole.allCases {
      let profile = WorkspaceMotionPolicy.profile(for: role, reduceMotion: true)
      #expect(profile.duration == 0.12)
      #expect(profile.displacement == 0)
      #expect(profile.inactiveScale == 1)
    }
  }

  @Test func sidebarSelectionUsesExplicitCrossfadeEndpoints() {
    #expect(
      WorkspaceMotionPolicy.selectionBlend(isSelected: false)
        == WorkspaceSelectionBlend(selectedOpacity: 0, unselectedOpacity: 1))
    #expect(
      WorkspaceMotionPolicy.selectionBlend(isSelected: true)
        == WorkspaceSelectionBlend(selectedOpacity: 1, unselectedOpacity: 0))
  }
}
