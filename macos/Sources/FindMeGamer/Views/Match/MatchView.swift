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
  let onComposeOutreach: (UUID, [UUID]) -> Void
  let onResendDelivery: (UUID) -> Void

  @Environment(\.workspaceWritesEnabled) private var writesEnabled

  var body: some View {
    VStack(spacing: 0) {
      MatchHero(model: model, writesEnabled: writesEnabled)
      Divider()
      MatchHistoryList(model: model, writesEnabled: writesEnabled)
    }
    .navigationDestination(for: MatchRoute.self) { route in
      switch route {
      case .result(let matchID):
        MatchResultView(
          matchID: matchID, model: model, writesEnabled: writesEnabled,
          onOpenProfile: onOpenProfile, onComposeOutreach: onComposeOutreach,
          onResendDelivery: onResendDelivery)
      }
    }
    .task {
      async let games: Void = model.loadGames()
      async let history: Void = model.loadHistory()
      _ = await (games, history)
    }
  }
}
