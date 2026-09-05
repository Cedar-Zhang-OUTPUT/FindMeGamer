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

enum MatchResultInteractionPolicy {
  /// Retained results are readable context, never authority for sending or selecting recipients.
  static func canAct(
    on matchID: UUID, state: MatchResultViewState, writesEnabled: Bool
  ) -> Bool {
    guard writesEnabled, case .available(let result) = state else { return false }
    return result.id == matchID
  }
}
