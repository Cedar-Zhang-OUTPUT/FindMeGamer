import SwiftUI

public enum AppDestination: String, CaseIterable, Identifiable, Sendable, Hashable {
  case discover
  case match
  case outreach
  case library
  case settings

  public var id: String { rawValue }

  public var title: String {
    switch self {
    case .discover: "Discover"
    case .library: "Library"
    case .match: "Match"
    case .outreach: "Outreach Management"
    case .settings: "Settings"
    }
  }

  public var systemImage: String {
    switch self {
    case .discover: "sparkle.magnifyingglass"
    case .library: "square.grid.2x2"
    case .match: "person.2.badge.magnifyingglass"
    case .outreach: "paperplane"
    case .settings: "gearshape"
    }
  }

  public static func restoring(rawValue: String?) -> AppDestination {
    rawValue.flatMap(AppDestination.init(rawValue:)) ?? .discover
  }
}

public enum AppearanceMode: String, CaseIterable, Sendable, Hashable {
  case system
  case light
  case dark

  public var title: String { rawValue.capitalized }

  public var colorScheme: ColorScheme? {
    switch self {
    case .system: nil
    case .light: .light
    case .dark: .dark
    }
  }

  public static func restoring(rawValue: String?) -> AppearanceMode {
    rawValue.flatMap(AppearanceMode.init(rawValue:)) ?? .system
  }
}

public enum FontSizePreference: String, CaseIterable, Sendable, Hashable {
  case small
  case medium
  case `default`
  case large
  case extraLarge = "extra-large"

  public var title: String {
    switch self {
    case .small: "Small"
    case .medium: "Medium"
    case .default: "Default"
    case .large: "Large"
    case .extraLarge: "Extra Large"
    }
  }

  public var dynamicTypeSize: DynamicTypeSize {
    switch self {
    case .small: .small
    case .medium: .medium
    case .default: .large
    case .large: .xLarge
    case .extraLarge: .xxLarge
    }
  }

  public static func restoring(rawValue: String?) -> FontSizePreference {
    rawValue.flatMap(FontSizePreference.init(rawValue:)) ?? .default
  }
}

public struct WorkspaceAvailability: Sendable, Equatable, Hashable {
  public let writesEnabled: Bool
  public let readsEnabled = true
  public let navigationEnabled = true

  public init(state: AppSession.State) {
    writesEnabled = state == .authenticated
  }
}

public enum OutreachComposerActionPolicy {
  public static func canSend(
    workspaceWritesEnabled: Bool,
    modelCanConfirmSend: Bool
  ) -> Bool {
    workspaceWritesEnabled && modelCanConfirmSend
  }
}

public enum WorkspaceRootSurface: Sendable, Equatable, Hashable {
  case checking
  case access
  case workspace

  public static func resolve(
    state: AppSession.State,
    hasValidatedWorkspace: Bool
  ) -> WorkspaceRootSurface {
    switch state {
    case .checking:
      hasValidatedWorkspace ? .workspace : .checking
    case .needsKey:
      .access
    case .authenticated, .offline:
      hasValidatedWorkspace ? .workspace : .access
    }
  }
}
