import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct MatchFocusPresentationTests {
  @Test func acceptedSubmissionFocusesItsGameWithoutFollowingUnrelatedBackgroundWork() {
    var focus = MatchWorkspaceFocus.newMatch
    let unrelated = focusTask(id: 1, gameID: 11)
    let submitted = focusTask(id: 2, gameID: 12)
    focus.submissionFinished(
      gameID: submitted.game.id, tasks: [unrelated, submitted], failed: false)
    #expect(focus == .task(submitted.id))

    focus.submissionFinished(
      gameID: unrelated.game.id, tasks: [unrelated, submitted], failed: false)
    #expect(focus == .task(submitted.id))
  }

  @Test func failedOrMissingSubmissionKeepsTheEditableGameChoice() {
    let task = focusTask(id: 1, gameID: 11)
    var focus = MatchWorkspaceFocus.newMatch
    focus.submissionFinished(gameID: task.game.id, tasks: [task], failed: true)
    #expect(focus == .newMatch)
    focus.submissionFinished(gameID: focusID(99), tasks: [task], failed: false)
    #expect(focus == .newMatch)
  }

  @Test func aNewSubmissionWinsOverOlderSameGameTasksWithTiedTimestamps() {
    let old = focusTask(id: 1, gameID: 11)
    let submitted = focusTask(id: 2, gameID: 11)
    var focus = MatchWorkspaceFocus.newMatch
    focus.submissionFinished(
      gameID: old.game.id, tasks: [old, submitted], failed: false,
      previouslyKnownIDs: [old.id])
    #expect(focus == .task(submitted.id))
  }

  @Test func compactHistoryKeepsServerOrderAndDoesNotRepeatTheFocusedTask() {
    let tasks = (1...6).map { focusTask(id: $0, gameID: 11) }
    let compact = MatchHistoryVisibility(tasks: tasks, focusedTaskID: tasks[0].id, expanded: false)
    #expect(compact.visible.map(\.id) == Array(tasks.dropFirst().prefix(3)).map(\.id))
    #expect(compact.hiddenCount == 2)
    let expanded = MatchHistoryVisibility(tasks: tasks, focusedTaskID: tasks[0].id, expanded: true)
    #expect(expanded.visible.map(\.id) == Array(tasks.dropFirst()).map(\.id))
    #expect(expanded.hiddenCount == 0)
  }

  @Test func restoredSelectionStoresOnlyStableCreatorIDsAndIgnoresInvalidEntries() {
    let first = focusID(1)
    let second = focusID(2)
    let selection = MatchRecipientSelection(storedIDs: "\(second),invalid,\(first),\(first)")
    #expect(selection.count == 2)
    #expect(selection.contains(first))
    #expect(selection.contains(second))
    #expect(MatchRecipientSelection(storedIDs: selection.storedIDs) == selection)
    #expect(!selection.storedIDs.contains("invalid"))
  }

  @Test func retainedResultsCannotSelectOrSendUntilTheSameResultIsFreshAgain() {
    let result = focusResult(id: 1)
    for state in [MatchResultViewState.idle, .loading, .failed("Refresh failed"), .empty("Empty")] {
      #expect(
        !MatchResultInteractionPolicy.canAct(on: result.id, state: state, writesEnabled: true))
    }
    #expect(
      MatchResultInteractionPolicy.canAct(
        on: result.id, state: .available(result), writesEnabled: true))
    #expect(
      !MatchResultInteractionPolicy.canAct(
        on: result.id, state: .available(result), writesEnabled: false))
    #expect(
      !MatchResultInteractionPolicy.canAct(
        on: focusID(2), state: .available(result), writesEnabled: true))
  }

  @Test func actionBarAppearsForSelectionOrAnActionableBlockingStateWithoutTeachingCopy() {
    let ready = MatchResultActionState(resultState: .available(focusResult(id: 1)), writesEnabled: true)
    #expect(ready == .ready)
    #expect(!ready.showsBar(selectedCount: 0))
    #expect(ready.showsBar(selectedCount: 2))
    #expect(ready.statusLabel == nil)
    #expect(!ready.showsRetry)

    let refreshing = MatchResultActionState(resultState: .loading, writesEnabled: true)
    #expect(refreshing == .refreshing)
    #expect(refreshing.showsBar(selectedCount: 0))
    #expect(!refreshing.showsRetry)

    let failed = MatchResultActionState(resultState: .failed("Offline"), writesEnabled: true)
    #expect(failed == .refreshRequired)
    #expect(failed.statusLabel == "Saved result · Refresh required")
    #expect(failed.showsBar(selectedCount: 0))
    #expect(failed.showsRetry)

    let readOnly = MatchResultActionState(
      resultState: .available(focusResult(id: 1)), writesEnabled: false)
    #expect(readOnly == .readOnly)
    #expect(readOnly.showsBar(selectedCount: 0))
    #expect(!readOnly.showsRetry)
  }

  @Test func cachedFailureKeepsTheFullReasonAndRetryVisibleWithoutSelectedRecipients() {
    let message = "Connection lost. The displayed result is saved; reconnect and retry."
    for writesEnabled in [false, true] {
      let failed = MatchResultActionPresentation(
        resultState: .failed(message), writesEnabled: writesEnabled)
      #expect(failed.state.showsBar(selectedCount: 0))
      #expect(failed.state.showsRetry)
      #expect(failed.failureMessage == message)

      let refreshing = MatchResultActionPresentation(
        resultState: .loading, writesEnabled: writesEnabled)
      #expect(refreshing.state.showsBar(selectedCount: 0))
      #expect(refreshing.state.statusLabel == "Saved result · refreshing…")
      #expect(!refreshing.state.showsRetry)
      #expect(refreshing.failureMessage == nil)
    }
    let recovered = MatchResultActionPresentation(
      resultState: .available(focusResult(id: 1)), writesEnabled: true)
    #expect(recovered.state == .ready)
    #expect(!recovered.state.showsBar(selectedCount: 0))
    #expect(recovered.failureMessage == nil)
  }

  @Test func latestMatchActionFollowsExplicitReplacementLinksNotNewerSameGameTasks() {
    let original = focusTask(id: 1, gameID: 11)
    let unrelated = focusTask(id: 9, gameID: 11)
    #expect(MatchTaskSuccessorPolicy.latestSuccessor(of: original, in: [original, unrelated]) == nil)

    let replacement = focusTask(id: 2, gameID: 11, supersedesID: original.id)
    let latest = focusTask(id: 3, gameID: 11, supersedesID: replacement.id)
    #expect(
      MatchTaskSuccessorPolicy.latestSuccessor(
        of: original, in: [unrelated, latest, original, replacement])?.id == latest.id)

    let ambiguous = focusTask(id: 4, gameID: 11, supersedesID: original.id)
    #expect(
      MatchTaskSuccessorPolicy.latestSuccessor(
        of: original, in: [original, replacement, ambiguous]) == nil)
    let cycle = focusTask(id: 1, gameID: 11, supersedesID: replacement.id)
    #expect(MatchTaskSuccessorPolicy.latestSuccessor(of: cycle, in: [cycle, replacement]) == nil)
  }
}

private func focusID(_ value: Int) -> UUID {
  UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", value))!
}

private func focusTask(id: Int, gameID: Int, supersedesID: UUID? = nil) -> MatchTask {
  MatchTask(
    id: focusID(id),
    game: MatchGameHeader(
      id: focusID(gameID), name: "Game \(gameID)", steamAppID: "730",
      canonicalURL: "https://store.steampowered.com/app/730", coverURL: nil),
    status: .queued, stage: .screening, completedUnits: 0, totalUnits: 0,
    resultCount: 0, retryable: false, failure: nil, correlationID: nil, supersedesID: supersedesID,
    createdAt: Date(timeIntervalSince1970: Double(id)),
    updatedAt: Date(timeIntervalSince1970: Double(id)), startedAt: nil, completedAt: nil)
}

private func focusResult(id: Int) -> MatchResult {
  let task = focusTask(id: id, gameID: 11)
  return MatchResult(
    id: task.id, game: task.game, status: .succeeded, stage: .ranking,
    completedUnits: 1, totalUnits: 1, resultCount: 0, retryable: false, failure: nil,
    correlationID: nil, supersedesID: nil, createdAt: task.createdAt,
    updatedAt: task.updatedAt, startedAt: nil, completedAt: task.updatedAt,
    state: .available, recommendedMatches: [], otherMatches: [])
}
