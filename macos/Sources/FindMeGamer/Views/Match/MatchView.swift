import FindMeGamerCore
import SwiftUI

enum MatchRoute: Hashable {
  case result(UUID)
}

enum MatchCopy {
  static let heroPrefix = "Find me a creator for"
  static let selectGame = "Select Game"
  static let submit = "Submit"
  static let history = "Match History"
  static let recommended = "Recommended Matches"
  static let other = "Other Matches"
  static let sections = [recommended, other]
  static let viewDetails = "View Match Details"
  static let sendEmail = "Send Email"
  static let resend = "Resend"
  static let noSuitableCreators = "No suitable creators found"

  static func sendOutreach(count: Int) -> String { "Send Outreach (\(count))" }

  static let productionLabels = [
    heroPrefix, selectGame, submit, history, recommended, other, viewDetails, sendEmail, resend,
    noSuitableCreators,
  ]
}

enum MatchAccessibility {
  static let gameSelector = "match.game-selector"
  static let submit = "match.submit"
  static let history = "match.history"
  static let result = "match.result"
  static let gameProfile = "match.game-profile"
  static let batchSend = "match.batch-send"

  static func task(_ id: UUID) -> String { "match.task.\(id.uuidString)" }
  static func creator(_ id: UUID) -> String { "match.creator.\(id.uuidString)" }
  static func creatorSelect(_ id: UUID) -> String { "match.creator-select.\(id.uuidString)" }
  static func creatorSend(_ id: UUID) -> String { "match.creator-send.\(id.uuidString)" }
  static func creatorResend(_ id: UUID) -> String { "match.creator-resend.\(id.uuidString)" }
}

struct MatchView: View {
  @Bindable var model: MatchModel
  let onOpenProfile: (ProfileType, UUID) -> Void
  let onComposeOutreach: (UUID, [OutreachRecipientContext]) -> Void
  let onResendDelivery: (UUID) -> Void
  var acceptedBatch: SendBatch? = nil
  var onViewCampaign: (UUID) -> Void = { _ in }
  var onAddProfile: (ProfileType) -> Void = { _ in }

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @SceneStorage("match.focusedTaskID") private var focusedTaskID = ""

  private var focus: MatchWorkspaceFocus {
    get { UUID(uuidString: focusedTaskID).map(MatchWorkspaceFocus.task) ?? .newMatch }
    nonmutating set { focusedTaskID = newValue.taskID?.uuidString ?? "" }
  }

  private var focusedTask: MatchTask? {
    model.tasks.first { $0.id == focus.taskID }
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXL) {
        WorkspacePageHeader(WorkspacePageCopy.match) {
          if focus != .newMatch {
            Button("New match", systemImage: "plus", action: startNewMatch)
            .buttonStyle(.bordered)
          }
        }

        if let focusedTask {
          MatchTaskFocusCard(
            model: model, task: focusedTask, writesEnabled: writesEnabled,
            onOpenGame: { onOpenProfile(.game, focusedTask.game.id) },
            onNewMatch: startNewMatch,
            onAddCreators: { onAddProfile(.creator) },
            onFocusTask: { focus = .task($0) })
        } else {
          MatchHero(
            model: model, writesEnabled: writesEnabled, onSubmit: submit,
            onAddGame: { onAddProfile(.game) })
        }

        MatchHistoryList(
          model: model, writesEnabled: writesEnabled, focusedTaskID: focusedTask?.id,
          onFocusTask: { focus = .task($0) })
      }
      .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
      .padding(.vertical, WorkspaceDesign.pageVerticalPadding)
      .frame(maxWidth: 1_040, alignment: .leading)
      .frame(maxWidth: .infinity)
    }
    .workspaceCanvas()
    .navigationTitle("Match")
    .navigationDestination(for: MatchRoute.self) { route in
      switch route {
      case .result(let matchID):
        MatchResultView(
          matchID: matchID, model: model, writesEnabled: writesEnabled,
          onOpenProfile: onOpenProfile, onComposeOutreach: onComposeOutreach,
          onResendDelivery: onResendDelivery,
          acceptedBatch: acceptedBatch, onViewCampaign: onViewCampaign,
          onAddCreators: { onAddProfile(.creator) })
      }
    }
    .task {
      async let games: Void = model.loadGames()
      async let history: Void = model.loadHistory()
      _ = await (games, history)
    }
  }

  private func startNewMatch() {
    if let focusedTask,
      let game = model.games.first(where: { $0.id == focusedTask.game.id })
    {
      model.selectedGame = game
    }
    withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
      focus = .newMatch
    }
  }

  private func submit() {
    guard let gameID = model.selectedGame?.id else { return }
    Task {
      guard !model.isSubmitting else { return }
      let previouslyKnownIDs = Set(model.tasks.map(\.id))
      await model.submit()
      var nextFocus = focus
      nextFocus.submissionFinished(
        gameID: gameID, tasks: model.tasks, failed: model.actionError != nil,
        previouslyKnownIDs: previouslyKnownIDs)
      withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
        focus = nextFocus
      }
    }
  }
}
