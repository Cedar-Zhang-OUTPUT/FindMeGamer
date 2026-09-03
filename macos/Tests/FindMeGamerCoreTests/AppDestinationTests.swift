import SwiftUI
import Testing

@testable import FindMeGamerCore

@Suite struct AppDestinationTests {
  @Test func destinationsExposeTheApprovedSidebarContractInOrder() {
    #expect(AppDestination.allCases == [.library, .match, .outreach, .settings])
    #expect(
      AppDestination.allCases.map(\.title) == [
        "Library", "Match", "Outreach Management", "Settings",
      ])
    #expect(
      AppDestination.allCases.map(\.systemImage) == [
        "square.grid.2x2", "person.2.badge.magnifyingglass", "paperplane", "gearshape",
      ])
    #expect(AppDestination.allCases.map(\.id) == ["library", "match", "outreach", "settings"])
    #expect(AppDestination.allCases.count == 4)
  }

  @Test func restoredDestinationDefaultsToLibraryAndPreservesEveryValidValue() {
    #expect(AppDestination.restoring(rawValue: nil) == .library)
    #expect(AppDestination.restoring(rawValue: "") == .library)
    #expect(AppDestination.restoring(rawValue: "analyze") == .library)
    #expect(AppDestination.restoring(rawValue: "match-results") == .library)
    #expect(AppDestination.restoring(rawValue: "library") == .library)
    #expect(AppDestination.restoring(rawValue: "match") == .match)
    #expect(AppDestination.restoring(rawValue: "outreach") == .outreach)
    #expect(AppDestination.restoring(rawValue: "settings") == .settings)
  }

  @Test func appearancePolicyMapsExactStoredValuesAndSafeFallbacks() {
    #expect(AppearanceMode.allCases.map(\.title) == ["System", "Light", "Dark"])
    #expect(AppearanceMode.allCases.map(\.rawValue) == ["system", "light", "dark"])
    #expect(AppearanceMode.restoring(rawValue: nil) == .system)
    #expect(AppearanceMode.restoring(rawValue: "corrupt") == .system)
    #expect(AppearanceMode.restoring(rawValue: "system").colorScheme == nil)
    #expect(AppearanceMode.restoring(rawValue: "light").colorScheme == .light)
    #expect(AppearanceMode.restoring(rawValue: "dark").colorScheme == .dark)

    #expect(
      FontSizePreference.allCases.map(\.title) == [
        "Small", "Medium", "Default", "Large", "Extra Large",
      ])
    #expect(
      FontSizePreference.allCases.map(\.rawValue) == [
        "small", "medium", "default", "large", "extra-large",
      ])
    #expect(FontSizePreference.restoring(rawValue: nil) == .default)
    #expect(FontSizePreference.restoring(rawValue: "corrupt") == .default)
    #expect(FontSizePreference.restoring(rawValue: "small").dynamicTypeSize == .small)
    #expect(FontSizePreference.restoring(rawValue: "medium").dynamicTypeSize == .medium)
    #expect(FontSizePreference.restoring(rawValue: "default").dynamicTypeSize == .large)
    #expect(FontSizePreference.restoring(rawValue: "large").dynamicTypeSize == .xLarge)
    #expect(FontSizePreference.restoring(rawValue: "extra-large").dynamicTypeSize == .xxLarge)
  }

  @Test func workspaceAvailabilityDisablesOnlyWritesWhileOffline() {
    let authenticated = WorkspaceAvailability(state: .authenticated)
    #expect(authenticated.writesEnabled)
    #expect(authenticated.readsEnabled)
    #expect(authenticated.navigationEnabled)

    let offline = WorkspaceAvailability(state: .offline)
    #expect(!offline.writesEnabled)
    #expect(offline.readsEnabled)
    #expect(offline.navigationEnabled)
  }

  @Test func retainedServiceKeepsAuthenticatedAndOfflineStatesOnTheSameWorkspaceSurface() {
    #expect(WorkspaceRootSurface.resolve(state: .checking, hasService: false) == .checking)
    #expect(WorkspaceRootSurface.resolve(state: .needsKey, hasService: false) == .access)
    #expect(WorkspaceRootSurface.resolve(state: .authenticated, hasService: true) == .workspace)
    #expect(WorkspaceRootSurface.resolve(state: .authenticated, hasService: false) == .access)
    #expect(WorkspaceRootSurface.resolve(state: .offline, hasService: true) == .workspace)
    #expect(WorkspaceRootSurface.resolve(state: .offline, hasService: false) == .access)
  }

  @MainActor
  @Test func retrySequenceRetainsTheSameNavigationHistoryOwner() {
    let navigation = WorkspaceNavigationState()
    navigation.libraryPath.append("creator-detail")
    navigation.matchPath.append("match-results")
    navigation.outreachPath.append("campaign-detail")
    navigation.settingsPath.append("email-settings")
    let originalOwner = ObjectIdentifier(navigation)

    let retrySequence: [AppSession.State] = [.offline, .checking, .authenticated]
    #expect(
      retrySequence.map {
        WorkspaceRootSurface.resolve(state: $0, hasService: true)
      } == [.workspace, .checking, .workspace])

    #expect(ObjectIdentifier(navigation) == originalOwner)
    #expect(navigation.libraryPath.count == 1)
    #expect(navigation.matchPath.count == 1)
    #expect(navigation.outreachPath.count == 1)
    #expect(navigation.settingsPath.count == 1)
  }
}
