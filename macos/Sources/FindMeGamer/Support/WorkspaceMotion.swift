import SwiftUI

enum WorkspaceMotionDirection: Equatable {
  case backward
  case stationary
  case forward
}

enum WorkspaceMotionRole: CaseIterable {
  case destination
  case switcher
  case selectionFeedback
}

struct WorkspaceMotionProfile: Equatable {
  let duration: TimeInterval
  let displacement: CGFloat
  let inactiveScale: CGFloat
}

struct WorkspaceSelectionBlend: Equatable {
  let selectedOpacity: Double
  let unselectedOpacity: Double
}

enum WorkspaceMotionPolicy {
  static func direction<Value: Equatable>(
    from current: Value,
    to next: Value,
    ordered values: [Value]
  ) -> WorkspaceMotionDirection {
    guard current != next,
      let currentIndex = values.firstIndex(of: current),
      let nextIndex = values.firstIndex(of: next)
    else { return .stationary }

    return nextIndex > currentIndex ? .forward : .backward
  }

  static func profile(
    for role: WorkspaceMotionRole,
    reduceMotion: Bool
  ) -> WorkspaceMotionProfile {
    if reduceMotion {
      return WorkspaceMotionProfile(duration: 0.12, displacement: 0, inactiveScale: 1)
    }

    return switch role {
    case .destination:
      WorkspaceMotionProfile(duration: 0.22, displacement: 10, inactiveScale: 1)
    case .switcher:
      WorkspaceMotionProfile(duration: 0.18, displacement: 8, inactiveScale: 1)
    case .selectionFeedback:
      WorkspaceMotionProfile(duration: 0.16, displacement: 0, inactiveScale: 0.94)
    }
  }

  static func animation(
    for role: WorkspaceMotionRole,
    reduceMotion: Bool
  ) -> Animation {
    let profile = profile(for: role, reduceMotion: reduceMotion)
    if reduceMotion {
      return .easeOut(duration: profile.duration)
    }
    return .smooth(duration: profile.duration, extraBounce: 0)
  }

  static func selectionBlend(isSelected: Bool) -> WorkspaceSelectionBlend {
    WorkspaceSelectionBlend(
      selectedOpacity: isSelected ? 1 : 0,
      unselectedOpacity: isSelected ? 0 : 1)
  }

  static func transition(
    direction: WorkspaceMotionDirection,
    role: WorkspaceMotionRole,
    reduceMotion: Bool
  ) -> AnyTransition {
    let displacement = profile(for: role, reduceMotion: reduceMotion).displacement
    guard direction != .stationary, displacement > 0 else { return .opacity }

    let insertionOffset = direction == .forward ? displacement : -displacement
    return .asymmetric(
      insertion: .modifier(
        active: WorkspaceTransitionModifier(opacity: 0, horizontalOffset: insertionOffset),
        identity: WorkspaceTransitionModifier(opacity: 1, horizontalOffset: 0)),
      removal: .modifier(
        active: WorkspaceTransitionModifier(opacity: 0, horizontalOffset: -insertionOffset),
        identity: WorkspaceTransitionModifier(opacity: 1, horizontalOffset: 0)))
  }
}

private struct WorkspaceTransitionModifier: ViewModifier {
  let opacity: Double
  let horizontalOffset: CGFloat

  func body(content: Content) -> some View {
    content
      .opacity(opacity)
      .offset(x: horizontalOffset)
  }
}
