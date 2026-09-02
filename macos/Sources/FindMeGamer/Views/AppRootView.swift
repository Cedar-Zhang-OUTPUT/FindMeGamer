import FindMeGamerCore
import SwiftUI

struct AppRootView: View {
  let session: AppSession

  var body: some View {
    Group {
      switch session.state {
      case .checking:
        ProgressView("Checking workspace access…")
      case .needsKey:
        WorkspaceAccessView(session: session)
      case .authenticated:
        placeholder
      case .offline:
        if session.service != nil {
          placeholder
        } else {
          WorkspaceAccessView(session: session)
        }
      }
    }
    .frame(minWidth: 640, minHeight: 420)
  }

  private var placeholder: some View {
    Text("Find Me Gamer")
  }
}
