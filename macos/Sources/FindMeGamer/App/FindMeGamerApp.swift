import FindMeGamerCore
import SwiftUI

@main
@MainActor
struct FindMeGamerApp: App {
  @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
  @State private var session = AppSession.configured()

  var body: some Scene {
    WindowGroup("Find Me Gamer", id: "main") {
      AppRootView(session: session)
        .task { await session.restore() }
    }
  }
}
