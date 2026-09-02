import SwiftUI

@main
struct FindMeGamerApp: App {
  @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

  var body: some Scene {
    WindowGroup("Find Me Gamer", id: "main") {
      AppRootView()
    }
  }
}
