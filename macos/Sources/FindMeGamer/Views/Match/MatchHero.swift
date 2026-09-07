import FindMeGamerCore
import SwiftUI

enum MatchGameEntryState: Equatable {
  case loading
  case empty
  case unavailable
  case choosing

  init(hasGames: Bool, isLoading: Bool, hasError: Bool) {
    if hasGames {
      self = .choosing
    } else if isLoading {
      self = .loading
    } else if hasError {
      self = .unavailable
    } else {
      self = .empty
    }
  }
}

struct MatchHeroPolicy: Equatable {
  let showsSubmit: Bool
  let submitEnabled: Bool

  init(hasSelection: Bool, writesEnabled: Bool, canSubmit: Bool) {
    showsSubmit = true
    submitEnabled = hasSelection && writesEnabled && canSubmit
  }

  init(showsSubmit: Bool, submitEnabled: Bool) {
    self.showsSubmit = showsSubmit
    self.submitEnabled = submitEnabled
  }
}

struct MatchHero: View {
  @Bindable var model: MatchModel
  let writesEnabled: Bool
  let onSubmit: () -> Void
  var onAddGame: () -> Void = {}

  private var policy: MatchHeroPolicy {
    MatchHeroPolicy(
      hasSelection: model.selectedGame != nil, writesEnabled: writesEnabled,
      canSubmit: model.canSubmit)
  }

  private var entryState: MatchGameEntryState {
    MatchGameEntryState(
      hasGames: !model.games.isEmpty, isLoading: model.isLoadingGames,
      hasError: model.gamesError != nil)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      ViewThatFits(in: .horizontal) {
        HStack(alignment: .center, spacing: 20) {
          entryControls.frame(minWidth: 310, maxWidth: .infinity, alignment: .leading)
          MatchConnectionArtwork(width: 112)
        }
        entryControls
      }

      if let gamesError = model.gamesError, !model.isLoadingGames {
        gameFailure(gamesError)
      }

      if let actionError = model.actionError {
        Label(actionError, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(Color(red: 1, green: 0.72, blue: 0.66))
          .textSelection(.enabled)
      }
    }
    .padding(24)
    .frame(maxWidth: .infinity, alignment: .leading)
    .modifier(MatchInkSurface())
  }

  @ViewBuilder private var entryControls: some View {
    switch entryState {
    case .loading:
      HStack(spacing: 10) {
        ProgressView().controlSize(.small)
        Text("Loading games…").font(.headline)
      }
      .frame(minHeight: 56)
    case .empty:
      Button("Add game", systemImage: "plus", action: onAddGame)
        .buttonStyle(.borderedProminent)
        .tint(MatchInkControlColors.actionBackground)
        .controlSize(.large)
        .disabled(!writesEnabled)
        .accessibilityIdentifier("match.add-game")
    case .unavailable:
      Label("Games unavailable", systemImage: "gamecontroller")
        .font(.headline)
    case .choosing:
      controls
    }
  }

  private var controls: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 12) {
        gameSelector
        submit
      }
      VStack(alignment: .leading, spacing: 12) {
        gameSelector
        submit
      }
    }
  }

  private var gameSelector: some View {
    // macOS Menu extracts its native title from the label instead of rendering
    // an arbitrary SwiftUI hierarchy. Keep the title simple and style outside.
    Menu(model.selectedGame?.name ?? "Choose a game…") {
      ForEach(model.games) { game in
        Button { model.selectedGame = game } label: {
          if model.selectedGame?.id == game.id {
            Label(game.name, systemImage: "checkmark")
              .labelStyle(.titleAndIcon)
          } else {
            Text(game.name)
          }
        }
      }
    }
    .menuStyle(.borderlessButton)
    .menuIndicator(.visible)
    .labelStyle(.titleOnly)
    .font(.body.weight(.medium))
    .foregroundStyle(MatchInkControlColors.text)
    .tint(MatchInkControlColors.text)
    .controlSize(.large)
    .environment(\.colorScheme, .light)
    .disabled(model.isLoadingGames || model.games.isEmpty || model.isSubmitting)
    .frame(minWidth: 220, minHeight: 44, alignment: .leading)
    .padding(.horizontal, 14)
    .padding(.vertical, 6)
    .background(MatchInkControlColors.surface, in: RoundedRectangle(cornerRadius: 14))
    .overlay {
      RoundedRectangle(cornerRadius: 14).strokeBorder(Color.white.opacity(0.75))
    }
    .accessibilityIdentifier(MatchAccessibility.gameSelector)
    .accessibilityLabel("Game")
    .accessibilityValue(model.selectedGame?.name ?? "Not selected")
    .help("Choose an analyzed Game Profile")
  }

  @ViewBuilder private var submit: some View {
    if policy.showsSubmit {
      HStack(spacing: 8) {
        if model.isSubmitting || model.isLoadingGames {
          ProgressView()
            .controlSize(.small)
            .accessibilityLabel(model.isSubmitting ? "Starting match" : "Refreshing games")
        }
        Button(action: onSubmit) {
          Text(model.isSubmitting ? "Starting…" : "Find creators")
            .foregroundStyle(.white)
        }
        .buttonStyle(.borderedProminent)
        .tint(MatchInkControlColors.actionBackground)
        .controlSize(.large)
        .disabled(!policy.submitEnabled)
        .accessibilityIdentifier(MatchAccessibility.submit)
        .help("Start a Match for the selected Game")
      }
    }
  }

  private func gameFailure(_ message: String) -> some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 8) {
        gameFailureMessage(message)
        retryGames
      }
      VStack(alignment: .leading, spacing: 8) {
        gameFailureMessage(message)
        retryGames
      }
    }
    .controlSize(.small)
  }

  private func gameFailureMessage(_ message: String) -> some View {
    Label(message, systemImage: "exclamationmark.triangle")
      .font(.callout)
      .foregroundStyle(Color.white.opacity(0.8))
      .fixedSize(horizontal: false, vertical: true)
      .textSelection(.enabled)
  }

  private var retryGames: some View {
    Button("Retry", systemImage: "arrow.clockwise") {
      Task { await model.loadGames() }
    }
    .buttonStyle(.bordered)
  }
}
