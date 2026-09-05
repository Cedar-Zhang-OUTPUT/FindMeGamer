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

  private static let transientFailureRetryDelays: [Duration] = [
    .seconds(1), .seconds(2), .seconds(4),
  ]

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
  private var workID: UInt64?
  private var nextWorkID: UInt64 = 0
  private var phase = Phase.idle
  private var refreshPending = false
  private var restartPending = false
  private var running = false
  private var generation: UInt64 = 0
  private var consecutiveSyncFailures = 0

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
    consecutiveSyncFailures = 0
    generation &+= 1
    if workTask != nil {
      restartPending = true
      return
    }
    scheduleSync(generation: generation)
  }

  public func stop() {
    guard running || workTask != nil else { return }
    running = false
    refreshPending = false
    restartPending = false
    consecutiveSyncFailures = 0
    generation &+= 1
    workTask?.cancel()
    if workTask == nil {
      phase = .idle
    }
  }

  public func refreshNow() {
    guard running else { return }
    consecutiveSyncFailures = 0
    switch phase {
    case .idle:
      scheduleSync(generation: generation)
    case .syncing:
      refreshPending = true
    case .sleeping:
      refreshPending = true
      workTask?.cancel()
    }
  }

  private func scheduleSync(generation operationGeneration: UInt64) {
    guard running, generation == operationGeneration, workTask == nil else { return }
    phase = .syncing
    nextWorkID &+= 1
    let operationID = nextWorkID
    workID = operationID
    let api = self.api
    let startingCursor = cursor
    workTask = Task { [weak self] in
      let outcome = await Self.fetchChanges(api: api, startingAt: startingCursor)
      let wasCancelled = Task.isCancelled
      await self?.syncWorkExited(
        id: operationID, outcome: outcome, wasCancelled: wasCancelled,
        generation: operationGeneration)
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

  private func syncWorkExited(
    id operationID: UInt64, outcome: SyncOutcome, wasCancelled: Bool,
    generation operationGeneration: UInt64
  ) {
    guard retireWork(id: operationID) else { return }
    if schedulePendingRestart() { return }
    guard running, generation == operationGeneration, !wasCancelled else { return }

    switch outcome {
    case .success(let page):
      consecutiveSyncFailures = 0
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
    case .failure:
      consecutiveSyncFailures += 1
    }

    if refreshPending {
      refreshPending = false
      consecutiveSyncFailures = 0
      scheduleSync(generation: operationGeneration)
    } else if case .failure = outcome,
      let delay = transientFailureRetryDelay
    {
      scheduleSleep(for: delay, generation: operationGeneration)
    } else if !activeJobs.isEmpty {
      scheduleSleep(for: .seconds(3), generation: operationGeneration)
    }
  }

  private var transientFailureRetryDelay: Duration? {
    let index = consecutiveSyncFailures - 1
    guard Self.transientFailureRetryDelays.indices.contains(index) else { return nil }
    return Self.transientFailureRetryDelays[index]
  }

  private func scheduleSleep(
    for duration: Duration, generation operationGeneration: UInt64
  ) {
    guard running, generation == operationGeneration, workTask == nil else { return }
    phase = .sleeping
    nextWorkID &+= 1
    let operationID = nextWorkID
    workID = operationID
    let clock = self.clock
    workTask = Task { [weak self] in
      let completed: Bool
      do {
        try await clock.sleep(for: duration)
        try Task.checkCancellation()
        completed = true
      } catch {
        // Cancellation is the control signal for Refresh, Stop, or stream termination.
        completed = false
      }
      await self?.sleepWorkExited(
        id: operationID, completed: completed, generation: operationGeneration)
    }
  }

  private func sleepWorkExited(
    id operationID: UInt64, completed: Bool, generation operationGeneration: UInt64
  ) {
    guard retireWork(id: operationID) else { return }
    if schedulePendingRestart() { return }
    guard running, generation == operationGeneration else { return }
    if refreshPending {
      refreshPending = false
      scheduleSync(generation: operationGeneration)
    } else if completed {
      scheduleSync(generation: operationGeneration)
    }
  }

  private func retireWork(id operationID: UInt64) -> Bool {
    guard workID == operationID else { return false }
    workTask = nil
    workID = nil
    phase = .idle
    return true
  }

  private func schedulePendingRestart() -> Bool {
    guard restartPending else { return false }
    restartPending = false
    refreshPending = false
    guard running else { return true }
    scheduleSync(generation: generation)
    return true
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
