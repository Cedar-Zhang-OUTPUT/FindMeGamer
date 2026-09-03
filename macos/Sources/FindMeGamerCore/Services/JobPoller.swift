import Foundation

public struct JobChangeBatch: Sendable, Equatable {
  public let changes: [JobChange]
  public let affectedProfileIDs: [UUID]
  public let affectedMatchTaskIDs: [UUID]
  public let affectedGameIDs: [UUID]
  public let hasActiveJobs: Bool

  public init(
    changes: [JobChange],
    affectedProfileIDs: [UUID],
    affectedMatchTaskIDs: [UUID],
    affectedGameIDs: [UUID],
    hasActiveJobs: Bool
  ) {
    self.changes = changes
    self.affectedProfileIDs = affectedProfileIDs
    self.affectedMatchTaskIDs = affectedMatchTaskIDs
    self.affectedGameIDs = affectedGameIDs
    self.hasActiveJobs = hasActiveJobs
  }
}

public actor JobPoller {
  public nonisolated let events: AsyncStream<JobChangeBatch>

  private enum Phase {
    case idle
    case syncing
    case sleeping
  }

  private enum JobIdentity: Hashable, Sendable {
    case analysis(UUID)
    case match(UUID)
  }

  private struct SyncPage: Sendable {
    let changes: [JobChange]
    let affectedProfileIDs: [UUID]
    let cursor: String
  }

  private enum SyncOutcome: Sendable {
    case success(SyncPage)
    case failure
  }

  private let api: any APIService
  private let clock: any AppClock
  private let continuation: AsyncStream<JobChangeBatch>.Continuation
  private var cursor: String?
  private var activeJobs: Set<JobIdentity> = []
  private var workTask: Task<Void, Never>?
  private var phase = Phase.idle
  private var refreshPending = false
  private var running = false
  private var generation: UInt64 = 0

  public init(api: any APIService, clock: any AppClock = ContinuousAppClock()) {
    self.api = api
    self.clock = clock
    let pair = AsyncStream<JobChangeBatch>.makeStream(bufferingPolicy: .unbounded)
    events = pair.stream
    continuation = pair.continuation
    pair.continuation.onTermination = { [weak self] _ in
      Task { await self?.stop() }
    }
  }

  deinit {
    workTask?.cancel()
    continuation.finish()
  }

  public func start() {
    guard !running else { return }
    running = true
    refreshPending = false
    generation &+= 1
    scheduleSync(generation: generation)
  }

  public func stop() {
    guard running || workTask != nil else { return }
    running = false
    refreshPending = false
    generation &+= 1
    workTask?.cancel()
    workTask = nil
    phase = .idle
  }

  public func refreshNow() {
    guard running else { return }
    switch phase {
    case .idle:
      scheduleSync(generation: generation)
    case .syncing:
      refreshPending = true
    case .sleeping:
      workTask?.cancel()
      workTask = nil
      phase = .idle
      scheduleSync(generation: generation)
    }
  }

  private func scheduleSync(generation operationGeneration: UInt64) {
    guard running, generation == operationGeneration else { return }
    phase = .syncing
    let api = self.api
    let startingCursor = cursor
    workTask = Task { [weak self] in
      let outcome = await Self.fetchChanges(api: api, startingAt: startingCursor)
      guard !Task.isCancelled else { return }
      await self?.finishSync(outcome, generation: operationGeneration)
    }
  }

  private nonisolated static func fetchChanges(
    api: any APIService, startingAt cursor: String?
  ) async -> SyncOutcome {
    var nextCursor = cursor
    var changes: [JobChange] = []
    var affectedProfileIDs: [UUID] = []
    var seenProfileIDs: Set<UUID> = []

    do {
      while true {
        try Task.checkCancellation()
        let page = try await api.listJobs(changedAfter: nextCursor, status: nil)
        try Task.checkCancellation()
        changes.append(contentsOf: page.items)
        appendUnique(page.affectedProfileIDs, to: &affectedProfileIDs, seen: &seenProfileIDs)
        nextCursor = page.cursor
        if !page.hasMore {
          return .success(
            SyncPage(
              changes: changes, affectedProfileIDs: affectedProfileIDs, cursor: page.cursor))
        }
      }
    } catch {
      return .failure
    }
  }

  private func finishSync(_ outcome: SyncOutcome, generation operationGeneration: UInt64) {
    guard running, generation == operationGeneration else { return }
    workTask = nil
    phase = .idle

    if case .success(let page) = outcome {
      cursor = page.cursor
      apply(page.changes)
      if !page.changes.isEmpty {
        let batch = makeBatch(
          changes: page.changes, affectedProfileIDs: page.affectedProfileIDs)
        if case .terminated = continuation.yield(batch) {
          stop()
          return
        }
      }
    }

    if refreshPending {
      refreshPending = false
      scheduleSync(generation: operationGeneration)
    } else if !activeJobs.isEmpty {
      scheduleSleep(generation: operationGeneration)
    }
  }

  private func scheduleSleep(generation operationGeneration: UInt64) {
    guard running, generation == operationGeneration else { return }
    phase = .sleeping
    let clock = self.clock
    workTask = Task { [weak self] in
      do {
        try await clock.sleep(for: .seconds(3))
        try Task.checkCancellation()
        await self?.sleepFinished(generation: operationGeneration)
      } catch {
        // Cancellation is the control signal for Refresh, Stop, or stream termination.
      }
    }
  }

  private func sleepFinished(generation operationGeneration: UInt64) {
    guard running, generation == operationGeneration, phase == .sleeping else { return }
    workTask = nil
    phase = .idle
    scheduleSync(generation: operationGeneration)
  }

  private func apply(_ changes: [JobChange]) {
    for change in changes {
      switch change {
      case .analysis(let job):
        updateActiveJob(.analysis(job.id), status: job.status)
      case .match(let job):
        updateActiveJob(.match(job.id), status: job.status)
      }
    }
  }

  private func updateActiveJob(_ identity: JobIdentity, status: JobStatus) {
    switch status {
    case .queued, .running:
      activeJobs.insert(identity)
    case .succeeded, .failed, .superseded:
      activeJobs.remove(identity)
    }
  }

  private func makeBatch(
    changes: [JobChange], affectedProfileIDs: [UUID]
  ) -> JobChangeBatch {
    var matchTaskIDs: [UUID] = []
    var gameIDs: [UUID] = []
    var seenMatchTaskIDs: Set<UUID> = []
    var seenGameIDs: Set<UUID> = []
    for change in changes {
      guard case .match(let match) = change else { continue }
      Self.appendUnique([match.id], to: &matchTaskIDs, seen: &seenMatchTaskIDs)
      Self.appendUnique([match.gameID], to: &gameIDs, seen: &seenGameIDs)
    }
    return JobChangeBatch(
      changes: changes,
      affectedProfileIDs: affectedProfileIDs,
      affectedMatchTaskIDs: matchTaskIDs,
      affectedGameIDs: gameIDs,
      hasActiveJobs: !activeJobs.isEmpty)
  }

  private nonisolated static func appendUnique<Value: Hashable>(
    _ values: [Value], to result: inout [Value], seen: inout Set<Value>
  ) {
    for value in values where seen.insert(value).inserted {
      result.append(value)
    }
  }
}
