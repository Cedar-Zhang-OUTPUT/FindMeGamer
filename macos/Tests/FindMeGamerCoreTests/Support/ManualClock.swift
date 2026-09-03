import Foundation

@testable import FindMeGamerCore

actor ManualClock: AppClock {
  private struct Waiter {
    let id: Int
    let deadline: Duration
    let continuation: CheckedContinuation<Void, any Error>
  }

  private var now: Duration = .zero
  private var nextID = 0
  private var waiters: [Waiter] = []
  private(set) var requestedDurations: [Duration] = []
  private(set) var cancellationCount = 0

  var pendingSleepCount: Int { waiters.count }

  func sleep(for duration: Duration) async throws {
    try Task.checkCancellation()
    guard duration > .zero else { return }

    let id = nextID
    nextID += 1
    try await withTaskCancellationHandler {
      try await withCheckedThrowingContinuation { continuation in
        requestedDurations.append(duration)
        waiters.append(
          Waiter(id: id, deadline: now + duration, continuation: continuation))
      }
    } onCancel: {
      Task { await self.cancel(id: id) }
    }
  }

  func advance(by duration: Duration) {
    now += duration
    let ready = waiters.filter { $0.deadline <= now }
    waiters.removeAll { $0.deadline <= now }
    for waiter in ready {
      waiter.continuation.resume()
    }
  }

  private func cancel(id: Int) {
    guard let index = waiters.firstIndex(where: { $0.id == id }) else { return }
    let waiter = waiters.remove(at: index)
    cancellationCount += 1
    waiter.continuation.resume(throwing: CancellationError())
  }
}
