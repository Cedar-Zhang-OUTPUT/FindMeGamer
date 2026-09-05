import FindMeGamerCore
import Foundation

/// User intent owns the focus. Polling may update a task, but must not select a different one.
enum MatchWorkspaceFocus: Equatable {
  case newMatch
  case task(UUID)

  var taskID: UUID? {
    guard case .task(let id) = self else { return nil }
    return id
  }

  mutating func submissionFinished(
    gameID: UUID, tasks: [MatchTask], failed: Bool, previouslyKnownIDs: Set<UUID> = []
  ) {
    guard self == .newMatch, !failed else { return }
    let candidates = tasks.filter { $0.game.id == gameID }
    guard
      let submitted = candidates.first(where: { !previouslyKnownIDs.contains($0.id) })
        ?? candidates.first
    else { return }
    self = .task(submitted.id)
  }
}

struct MatchHistoryVisibility {
  let visible: [MatchTask]
  let hiddenCount: Int
  let totalCount: Int

  init(tasks: [MatchTask], focusedTaskID: UUID?, expanded: Bool) {
    let history = tasks.filter { $0.id != focusedTaskID }
    totalCount = history.count
    visible = expanded ? history : Array(history.prefix(3))
    hiddenCount = history.count - visible.count
  }
}

enum MatchTaskSuccessorPolicy {
  /// Follow explicit replacement links only, never infer them from game names or dates.
  static func latestSuccessor(of task: MatchTask, in tasks: [MatchTask]) -> MatchTask? {
    var current = task
    var visited: Set<UUID> = [task.id]
    while true {
      let successors = tasks.filter { $0.supersedesID == current.id }
      guard !successors.isEmpty else { return current.id == task.id ? nil : current }
      guard successors.count == 1, let next = successors.first,
        visited.insert(next.id).inserted
      else { return nil }
      current = next
    }
  }
}

enum MatchResultActionState: Equatable {
  case ready
  case refreshing
  case refreshRequired
  case readOnly

  init(resultState: MatchResultViewState, writesEnabled: Bool) {
    switch resultState {
    case .loading: self = .refreshing
    case .failed: self = .refreshRequired
    default: self = writesEnabled ? .ready : .readOnly
    }
  }

  var statusLabel: String? {
    switch self {
    case .ready: nil
    case .refreshing: "Refreshing…"
    case .refreshRequired: "Refresh required"
    case .readOnly: "Read-only"
    }
  }

  var showsRetry: Bool { self == .refreshRequired }
  func showsBar(selectedCount: Int) -> Bool { selectedCount > 0 || self != .ready }
}

enum MatchResultInteractionPolicy {
  /// Retained results are readable context, never authority for sending or selecting recipients.
  static func canAct(
    on matchID: UUID, state: MatchResultViewState, writesEnabled: Bool
  ) -> Bool {
    guard writesEnabled, case .available(let result) = state else { return false }
    return result.id == matchID
  }
}
