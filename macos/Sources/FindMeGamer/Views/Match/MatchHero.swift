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
    AdaptiveGlassSurface(role: .matchHero) {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        HStack(spacing: WorkspaceDesign.spaceS) {
          WorkspaceStatusLozenge(
            title: "Library only",
            systemImage: "books.vertical.fill",
            tone: .neutral)
          Text("Matches use analyzed Creator Profiles already in this Workspace.")
            .font(.caption)
            .foregroundStyle(.secondary)
        }

        AdaptiveGlassActionGroup {
          ViewThatFits(in: .horizontal) {
            HStack(alignment: .center, spacing: WorkspaceDesign.spaceM) {
              Text(MatchCopy.heroPrefix)
                .font(.system(.title, design: .serif, weight: .semibold))
              gameSelector
              Spacer(minLength: WorkspaceDesign.spaceM)
              submit
            }

            VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
              Text(MatchCopy.heroPrefix)
                .font(.system(.title, design: .serif, weight: .semibold))
              gameSelector
              submit
            }
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
      .padding(.horizontal, WorkspaceDesign.spaceM)
      .padding(.vertical, WorkspaceDesign.spaceS)
    }
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
            .frame(width: 44, height: 44)
            .clipShape(RoundedRectangle(cornerRadius: 9, style: .continuous))
          Text(selected.name)
            .font(.headline)
        } else {
          Text(MatchCopy.selectGame)
            .font(.headline)
        }
        Image(systemName: "chevron.down")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .padding(.leading, 8)
      .padding(.trailing, 12)
      .padding(.vertical, 6)
      .background(Color.primary.opacity(0.06), in: Capsule())
      .overlay {
        Capsule().strokeBorder(Color.primary.opacity(0.1))
      }
    }
    .menuStyle(.borderlessButton)
    .menuIndicator(.hidden)
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
        .buttonStyle(.borderedProminent)
        .controlSize(.large)
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
