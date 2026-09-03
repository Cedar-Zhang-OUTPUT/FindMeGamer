import FindMeGamerCore
import SwiftUI

struct AppRootView: View {
  let session: AppSession
  @State private var workspaceAccessKey = ""

  var body: some View {
    Group {
      switch session.state {
      case .checking:
        ProgressView("Checking workspace access…")
      case .needsKey:
        WorkspaceAccessView(session: session, key: $workspaceAccessKey)
      case .authenticated:
        placeholder
      case .offline:
        if session.service != nil {
          placeholder
        } else {
          WorkspaceAccessView(session: session, key: $workspaceAccessKey)
        }
      }
    }
    .frame(minWidth: 640, minHeight: 420)
  }

  private var placeholder: some View {
    Text("Find Me Gamer")
  }
}
