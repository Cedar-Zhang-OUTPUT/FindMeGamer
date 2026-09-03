import SwiftUI
import Testing

@testable import FindMeGamer

@Suite struct GlassCompatibilityTests {
  @Test func surfacePolicyContainsOnlyTheThreeApprovedRolesInDisplayOrder() {
    #expect(
      GlassSurfaceRole.allCases == [.matchHero, .batchOutreach, .analyzeStatus])
  }

  @MainActor @Test func adaptiveWrappersAcceptOrdinarySwiftUIContent() {
    let surface = AdaptiveGlassSurface(role: .matchHero) {
      Text("Hero")
    }
    let actions = AdaptiveGlassActionGroup {
      Button("Choose") {}
      Button("Submit") {}
    }

    _ = surface
    _ = actions
  }
}
