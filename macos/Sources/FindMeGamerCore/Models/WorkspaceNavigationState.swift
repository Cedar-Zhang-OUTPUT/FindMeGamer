import Observation
import SwiftUI

@MainActor
@Observable
public final class WorkspaceNavigationState {
  public var libraryPath = NavigationPath()
  public var matchPath = NavigationPath()
  public var outreachPath = NavigationPath()
  public var settingsPath = NavigationPath()

  public init() {}
}
