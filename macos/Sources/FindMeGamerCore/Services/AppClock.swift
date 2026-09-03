public protocol AppClock: Sendable {
  func sleep(for duration: Duration) async throws
}

public struct ContinuousAppClock: AppClock, Sendable {
  public init() {}

  public func sleep(for duration: Duration) async throws {
    try await ContinuousClock().sleep(for: duration)
  }
}
