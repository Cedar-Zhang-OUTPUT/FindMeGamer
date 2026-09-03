import FindMeGamerCore
import SwiftUI

struct MatchHeroPolicy: Equatable {
  let showsSubmit: Bool
  let submitEnabled: Bool

  init(hasSelection: Bool, writesEnabled: Bool, canSubmit: Bool) {
    showsSubmit = hasSelection
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

  private var policy: MatchHeroPolicy {
    MatchHeroPolicy(
      hasSelection: model.selectedGame != nil, writesEnabled: writesEnabled,
      canSubmit: model.canSubmit)
  }

  var body: some View {
    VStack(spacing: 14) {
      ViewThatFits(in: .horizontal) {
        HStack(spacing: 12) {
          Text(MatchCopy.heroPrefix)
            .font(.title2.weight(.semibold))
          gameSelector
          submit
        }

        VStack(spacing: 12) {
          Text(MatchCopy.heroPrefix)
            .font(.title2.weight(.semibold))
          gameSelector
          submit
        }
      }

      gameLoadingAndFeedback

      if let actionError = model.actionError {
        Label(actionError, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(.red)
          .textSelection(.enabled)
      }
    }
    .frame(maxWidth: .infinity)
    .padding(.horizontal, 28)
    .padding(.vertical, 36)
  }

  private var gameSelector: some View {
    Menu {
      ForEach(model.games) { game in
        Button(game.name) { model.selectedGame = game }
      }
    } label: {
      HStack(spacing: 8) {
        if let selected = model.selectedGame {
          AsyncArtwork(url: artworkURL(for: selected), fallbackSystemImage: "gamecontroller")
            .frame(width: 28, height: 28)
            .clipShape(RoundedRectangle(cornerRadius: 5))
          Text(selected.name)
        } else {
          Text(MatchCopy.selectGame)
        }
        Image(systemName: "chevron.down")
          .font(.caption)
      }
    }
    .accessibilityIdentifier(MatchAccessibility.gameSelector)
    .help("Choose an analyzed Game Profile")
  }

  @ViewBuilder private var submit: some View {
    if policy.showsSubmit {
      HStack(spacing: 8) {
        if model.isSubmitting {
          ProgressView()
            .controlSize(.small)
        }
        Button(MatchCopy.submit) {
          Task { await model.submit() }
        }
        .disabled(!policy.submitEnabled)
        .accessibilityIdentifier(MatchAccessibility.submit)
        .help("Start a Match for the selected Game")
      }
    }
  }

  @ViewBuilder private var gameLoadingAndFeedback: some View {
    if model.isLoadingGames {
      HStack(spacing: 8) {
        ProgressView()
          .controlSize(.small)
        Text("Loading Game Profiles…")
          .foregroundStyle(.secondary)
      }
    }

    if let gamesError = model.gamesError {
      HStack(spacing: 8) {
        Text(gamesError)
          .foregroundStyle(.secondary)
        Button("Try Again") {
          Task { await model.loadGames() }
        }
      }
      .controlSize(.small)
    } else if !model.isLoadingGames && model.games.isEmpty {
      Text("No analyzed Game Profiles are available.")
        .foregroundStyle(.secondary)
    }
  }

  private func artworkURL(for game: FindMeGamerCore.GameProfileCard) -> URL? {
    for key in ["cover_image_url", "header_image_url"] {
      guard case .string(let rawValue) = game.currentFacts[key] else { continue }
      if let validated = ArtworkURLPolicy.validated(URL(string: rawValue)) { return validated }
    }
    return nil
  }
}
