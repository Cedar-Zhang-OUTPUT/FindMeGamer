import Foundation

/// Explicit local simulations for UI acceptance testing. Never consulted by the live service.
enum DemoScenario: String, Sendable {
  case normal
  case qaJourney = "qa-journey"
  case emptyLibrary = "empty-library"

  init(environment: [String: String]) {
    self = environment["FMG_DEMO_SCENARIO"].flatMap(Self.init(rawValue:)) ?? .normal
  }
}
