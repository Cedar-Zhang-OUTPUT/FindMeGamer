import FindMeGamerCore
import SwiftUI

struct AppRootView: View {
  let session: AppSession
  @State private var workspaceAccessKey = ""
  @State private var workspaceNavigation = WorkspaceNavigationState()

  var body: some View {
    Group {
      switch WorkspaceRootSurface.resolve(
        state: session.state,
        hasValidatedWorkspace: session.workspaceSession != nil)
      {
      case .checking:
        ProgressView("Checking workspace access…")
      case .access:
        WorkspaceAccessView(session: session, key: $workspaceAccessKey)
      case .workspace:
        AuthenticatedRootView(session: session, navigation: workspaceNavigation)
      }
    }
    .frame(
      minWidth: 640, maxWidth: .infinity, minHeight: 420, maxHeight: .infinity,
      alignment: .topLeading
    )
    .modifier(AppearancePreferences())
  }
}
