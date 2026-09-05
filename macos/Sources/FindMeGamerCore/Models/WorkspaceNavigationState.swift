import Observation
import SwiftUI

public struct OutreachCampaignDestination: Identifiable, Hashable {
  public let id: UUID

  public init(id: UUID) {
    self.id = id
  }
}

@MainActor
@Observable
public final class WorkspaceNavigationState {
  public var libraryPath = NavigationPath()
  public var matchPath = NavigationPath()
  public var outreachCampaign: OutreachCampaignDestination?
  public var settingsPath = NavigationPath()

  public init() {}

  public func openCampaign(id: UUID) {
    guard outreachCampaign?.id != id else { return }
    outreachCampaign = OutreachCampaignDestination(id: id)
  }
}
