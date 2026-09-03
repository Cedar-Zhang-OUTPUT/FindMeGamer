import FindMeGamerCore
import SwiftUI

private struct WorkspaceWritesEnabledKey: EnvironmentKey {
  static let defaultValue = true
}

extension EnvironmentValues {
  var workspaceWritesEnabled: Bool {
    get { self[WorkspaceWritesEnabledKey.self] }
    set { self[WorkspaceWritesEnabledKey.self] = newValue }
  }
}

struct AuthenticatedRootView: View {
  let session: AppSession
  @Bindable var navigation: WorkspaceNavigationState

  @SceneStorage("sidebar-selection") private var storedSelection = AppDestination.library.rawValue

  var body: some View {
    NavigationSplitView {
      SidebarView(selection: sidebarSelection)
    } detail: {
      VStack(spacing: 0) {
        if session.state == .offline {
          OfflineBanner(retry: retry)
        }

        selectedDetail
      }
      .environment(\.workspaceWritesEnabled, availability.writesEnabled)
    }
    .onAppear { storedSelection = selectedDestination.rawValue }
  }

  private var sidebarSelection: Binding<AppDestination?> {
    Binding(
      get: { selectedDestination },
      set: { storedSelection = ($0 ?? .library).rawValue })
  }

  private var selectedDestination: AppDestination {
    AppDestination.restoring(rawValue: storedSelection)
  }

  private var availability: WorkspaceAvailability {
    WorkspaceAvailability(state: session.state)
  }

  @ViewBuilder private var selectedDetail: some View {
    switch selectedDestination {
    case .library:
      NavigationStack(path: $navigation.libraryPath) {
        DestinationPlaceholder(destination: .library)
      }
    case .match:
      NavigationStack(path: $navigation.matchPath) {
        DestinationPlaceholder(destination: .match)
      }
    case .outreach:
      NavigationStack(path: $navigation.outreachPath) {
        DestinationPlaceholder(destination: .outreach)
      }
    case .settings:
      NavigationStack(path: $navigation.settingsPath) {
        DestinationPlaceholder(destination: .settings)
      }
    }
  }

  private func retry() {
    Task { await session.retryAccess(key: "") }
  }
}

private struct DestinationPlaceholder: View {
  let destination: AppDestination

  var body: some View {
    Text(destination.title)
      .font(.title)
      .frame(maxWidth: .infinity, maxHeight: .infinity)
      .navigationTitle(destination.title)
  }
}
