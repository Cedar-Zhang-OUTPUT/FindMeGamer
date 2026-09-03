import Foundation
import Observation

extension MatchStage {
  public var matchWorkflowLabel: String {
    switch self {
    case .screening: "Screening"
    case .pairwise: "Comparing Creators"
    case .ranking: "Ranking"
    }
  }
}

public enum MatchResultViewState: Sendable, Equatable {
  case idle
  case loading
  case available(MatchResult)
  case empty(String)
  case failed(String)
}

@MainActor
@Observable
public final class MatchModel {
  private struct SubmitAttempt: Equatable {
    let gameID: UUID
    let key: String
  }

  public private(set) var games: [GameProfileCard] = []
  public var selectedGame: GameProfileCard? {
    didSet {
      if oldValue?.id != selectedGame?.id {
        submitAttempt = nil
      }
    }
  }
  public var canSubmit: Bool { selectedGame != nil && !isSubmitting }

  public private(set) var tasks: [MatchTask] = []
  public private(set) var isLoadingGames = false
  public private(set) var isLoadingHistory = false
  public private(set) var isSubmitting = false
  public private(set) var retryingTaskIDs: Set<UUID> = []
  public private(set) var gamesError: String?
  public private(set) var historyError: String?
  public private(set) var actionError: String?
  public private(set) var selectedMatchID: UUID?
  public private(set) var resultState: MatchResultViewState = .idle

  @ObservationIgnored private let api: any APIService
  @ObservationIgnored private let idempotencyKey: @Sendable () -> String
  @ObservationIgnored private let onJobActivity: @Sendable () async -> Void
  @ObservationIgnored private var submitAttempt: SubmitAttempt?
  @ObservationIgnored private var retryKeys: [UUID: String] = [:]
  @ObservationIgnored private var retrySuppressionDates: [UUID: Date] = [:]
  @ObservationIgnored private var resultGeneration: UInt64 = 0

  public init(
    api: any APIService,
    idempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString },
    onJobActivity: @escaping @Sendable () async -> Void = {}
  ) {
    self.api = api
    self.idempotencyKey = idempotencyKey
    self.onJobActivity = onJobActivity
  }

  public func canRetry(task: MatchTask) -> Bool {
    task.status == .failed && task.retryable
      && !retryingTaskIDs.contains(task.id)
      && retrySuppressionDates[task.id] == nil
  }

  public func loadGames() async {
    guard !isLoadingGames else { return }
    isLoadingGames = true
    gamesError = nil
    defer { isLoadingGames = false }

    do {
      var cursor: String?
      var loaded: [GameProfileCard] = []
      var seen = Set<UUID>()
      repeat {
        let page = try await api.listProfiles(
          type: .game, query: "", onlyCollection: false, cursor: cursor, limit: 100)
        for card in page.items {
          guard case .game(let game) = card, seen.insert(game.id).inserted else { continue }
          loaded.append(game)
        }
        cursor = page.nextCursor
      } while cursor != nil

      games = loaded
      if let selectedID = selectedGame?.id {
        selectedGame = loaded.first { $0.id == selectedID }
      }
    } catch {
      gamesError = "Could not load Game Profiles."
    }
  }

  public func loadHistory() async {
    guard !isLoadingHistory else { return }
    isLoadingHistory = true
    historyError = nil
    defer { isLoadingHistory = false }

    do {
      var cursor: String?
      var loaded: [UUID: MatchTask] = [:]
      var hasMore = true
      while hasMore {
        let page = try await api.listMatches(cursor: cursor)
        for task in page.items {
          if let current = loaded[task.id], current.updatedAt > task.updatedAt { continue }
          loaded[task.id] = task
        }
        cursor = page.cursor
        hasMore = page.hasMore && cursor != nil
      }

      var merged = Dictionary(uniqueKeysWithValues: tasks.map { ($0.id, $0) })
      for task in loaded.values {
        if let current = merged[task.id], current.updatedAt > task.updatedAt { continue }
        merged[task.id] = task
        clearRetrySuppressionIfCanonical(taskID: task.id, updatedAt: task.updatedAt)
      }
      tasks = Self.sortedTasks(Array(merged.values))
    } catch {
      historyError = "Could not load Match history."
    }
  }

  public func submit() async {
    guard let game = selectedGame, !isSubmitting else { return }
    isSubmitting = true
    actionError = nil
    let attempt: SubmitAttempt
    if let retained = submitAttempt, retained.gameID == game.id {
      attempt = retained
    } else {
      attempt = SubmitAttempt(gameID: game.id, key: nextIdempotencyKey())
      submitAttempt = attempt
    }
    defer { isSubmitting = false }

    do {
      let task = try await api.createMatch(gameID: game.id, idempotencyKey: attempt.key)
      upsert(task)
      if submitAttempt == attempt { submitAttempt = nil }
      await onJobActivity()
    } catch {
      actionError = Self.message(from: error, fallback: "Could not start Match.")
    }
  }

  public func retry(task: MatchTask) async {
    guard canRetry(task: task) else { return }
    retryingTaskIDs.insert(task.id)
    actionError = nil
    let key = retryKeys[task.id] ?? nextIdempotencyKey()
    retryKeys[task.id] = key
    defer { retryingTaskIDs.remove(task.id) }

    do {
      let resumed = try await api.retryMatch(id: task.id, idempotencyKey: key)
      retryKeys[task.id] = nil
      retrySuppressionDates[task.id] = task.updatedAt
      upsert(resumed)
      await onJobActivity()
    } catch {
      actionError = Self.message(from: error, fallback: "Could not retry Match.")
    }
  }

  public func openResult(id: UUID) async {
    selectedMatchID = id
    resultGeneration &+= 1
    let generation = resultGeneration
    resultState = .loading

    do {
      let result = try await api.match(id: id)
      guard selectedMatchID == id, resultGeneration == generation else { return }
      guard result.id == id else {
        resultState = .failed("Could not load Match result.")
        return
      }
      resultState = Self.viewState(for: result)
    } catch {
      guard selectedMatchID == id, resultGeneration == generation else { return }
      resultState = .failed(Self.message(from: error, fallback: "Could not load Match result."))
    }
  }

  public func consume(jobBatch: JobChangeBatch) async {
    var newestByID: [UUID: ChangedMatchJob] = [:]
    var order: [UUID] = []
    for change in jobBatch.changes {
      guard case .match(let match) = change else { continue }
      if newestByID[match.id] == nil { order.append(match.id) }
      if let current = newestByID[match.id], current.updatedAt > match.updatedAt { continue }
      newestByID[match.id] = match
    }

    for id in order {
      guard let change = newestByID[id] else { continue }
      let known = tasks.first { $0.id == id }
      if let known, known.updatedAt > change.updatedAt { continue }

      if let known, change.status == .queued || change.status == .running {
        upsert(Self.task(from: change, game: known.game))
        clearRetrySuppressionIfCanonical(taskID: id, updatedAt: change.updatedAt)
        continue
      }

      let generation = resultGeneration
      do {
        let result = try await api.match(id: id)
        guard result.id == id else {
          historyError = "Could not refresh Match history."
          continue
        }
        if let current = tasks.first(where: { $0.id == id }), current.updatedAt > result.updatedAt {
          continue
        }
        upsert(Self.task(from: result))
        clearRetrySuppressionIfCanonical(taskID: id, updatedAt: result.updatedAt)
        if selectedMatchID == id, resultGeneration == generation {
          resultState = Self.viewState(for: result)
        }
      } catch {
        historyError = Self.message(from: error, fallback: "Could not refresh Match history.")
      }
    }
  }

  private func nextIdempotencyKey() -> String {
    let candidate = idempotencyKey()
    return UUID(uuidString: candidate) == nil ? UUID().uuidString : candidate
  }

  private func upsert(_ task: MatchTask) {
    if let index = tasks.firstIndex(where: { $0.id == task.id }) {
      guard tasks[index].updatedAt <= task.updatedAt else { return }
      tasks[index] = task
    } else {
      tasks.append(task)
    }
    tasks = Self.sortedTasks(tasks)
  }

  private func clearRetrySuppressionIfCanonical(taskID: UUID, updatedAt: Date) {
    guard let acceptedAt = retrySuppressionDates[taskID], updatedAt > acceptedAt else { return }
    retrySuppressionDates[taskID] = nil
  }

  private static func sortedTasks(_ tasks: [MatchTask]) -> [MatchTask] {
    tasks.sorted {
      if $0.createdAt != $1.createdAt { return $0.createdAt > $1.createdAt }
      return $0.id.uuidString > $1.id.uuidString
    }
  }

  private static func task(from change: ChangedMatchJob, game: MatchGameHeader) -> MatchTask {
    MatchTask(
      id: change.id, game: game, status: change.status, stage: change.stage,
      completedUnits: change.completedUnits, totalUnits: change.totalUnits,
      resultCount: change.resultCount, retryable: change.retryable, failure: change.failure,
      correlationID: change.correlationID, supersedesID: change.supersedesID,
      createdAt: change.createdAt, updatedAt: change.updatedAt, startedAt: change.startedAt,
      completedAt: change.completedAt)
  }

  private static func task(from result: MatchResult) -> MatchTask {
    MatchTask(
      id: result.id, game: result.game, status: result.status, stage: result.stage,
      completedUnits: result.completedUnits, totalUnits: result.totalUnits,
      resultCount: result.resultCount, retryable: result.retryable, failure: result.failure,
      correlationID: result.correlationID, supersedesID: result.supersedesID,
      createdAt: result.createdAt, updatedAt: result.updatedAt, startedAt: result.startedAt,
      completedAt: result.completedAt)
  }

  private static func viewState(for result: MatchResult) -> MatchResultViewState {
    if result.state == .noSuitableCreators
      || (result.status == .succeeded && result.recommendedMatches.isEmpty
        && result.otherMatches.isEmpty)
    {
      return .empty("No suitable creators found")
    }
    if result.status == .queued || result.status == .running || result.state == .pending {
      return .loading
    }
    if result.status == .succeeded {
      return .available(result)
    }
    return .failed(result.failure?.message ?? "Match result is unavailable.")
  }

  private static func message(from error: Error, fallback: String) -> String {
    (error as? APIError)?.description ?? fallback
  }
}
