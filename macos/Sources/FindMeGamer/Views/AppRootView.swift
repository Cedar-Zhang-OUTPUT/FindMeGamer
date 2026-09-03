import FindMeGamerCore
import SwiftUI

struct AppRootView: View {
  let session: AppSession
  @State private var workspaceAccessKey = ""
  @State private var workspaceNavigation = WorkspaceNavigationState()

  var body: some View {
    Group {
      switch WorkspaceRootSurface.resolve(state: session.state, hasService: session.service != nil)
      {
      case .checking:
        ProgressView("Checking workspace access…")
      case .access:
        WorkspaceAccessView(session: session, key: $workspaceAccessKey)
      case .workspace:
        AuthenticatedRootView(session: session, navigation: workspaceNavigation)
      }
    }
    .frame(minWidth: 640, minHeight: 420)
    .modifier(AppearancePreferences())
  }
}
