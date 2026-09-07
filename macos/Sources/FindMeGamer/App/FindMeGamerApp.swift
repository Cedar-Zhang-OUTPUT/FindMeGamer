import FindMeGamerCore
import SwiftUI

@main
@MainActor
struct FindMeGamerApp: App {
  @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
  @State private var session = AppSession.configured()
  @State private var updates = AppUpdateChecker()
  @Environment(\.scenePhase) private var scenePhase

  var body: some Scene {
    WindowGroup("Find Me Gamer", id: "main") {
      AppRootView(session: session)
        .environment(updates)
        .task { await session.restore() }
        .task { await updates.checkAutomaticallyIfNeeded() }
        .onChange(of: scenePhase) { _, phase in
          if phase == .active { Task { await updates.checkAutomaticallyIfNeeded() } }
        }
    }
    .defaultSize(width: 1_180, height: 800)
    .commands { AppUpdateCommands(checker: updates) }

    Window("Software Update", id: "app-updates") {
      AppUpdatesWindow(checker: updates)
    }
    .defaultSize(width: 480, height: 420)
  }
}
