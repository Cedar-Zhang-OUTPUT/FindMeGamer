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
  let onSubmit: () -> Void

  private var policy: MatchHeroPolicy {
    MatchHeroPolicy(
      hasSelection: model.selectedGame != nil, writesEnabled: writesEnabled,
      canSubmit: model.canSubmit)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
      ViewThatFits(in: .horizontal) {
        HStack(alignment: .center, spacing: 24) {
          introduction.frame(minWidth: 310, maxWidth: .infinity, alignment: .leading)
          MatchConnectionArtwork()
        }
        introduction
      }

      ViewThatFits(in: .horizontal) {
        HStack(alignment: .center, spacing: WorkspaceDesign.spaceM) {
          gameSelector
            .frame(maxWidth: .infinity, alignment: .leading)
          submit
        }
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
          gameSelector
          submit
        }
      }

      gameLoadingAndFeedback

      Label("No emails are sent. You choose who to contact.", systemImage: "checkmark.shield")
        .font(.caption)
        .foregroundStyle(Color.white.opacity(0.7))

      if let actionError = model.actionError {
        Label(actionError, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(Color(red: 1, green: 0.72, blue: 0.66))
          .textSelection(.enabled)
      }
    }
    .padding(28)
    .frame(maxWidth: .infinity, alignment: .leading)
    .modifier(MatchInkSurface())
  }

  private var introduction: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("FIND YOUR PEOPLE")
        .font(.system(size: 10, weight: .bold, design: .rounded))
        .tracking(2)
        .foregroundStyle(Color(red: 0.61, green: 0.92, blue: 0.81))
      Text("Great games.\nThe right voices.")
        .font(.system(size: 34, weight: .semibold, design: .rounded))
        .tracking(-1.2)
        .fixedSize(horizontal: false, vertical: true)
      Text(
        "Start with a game. Discover the creators whose content and audience make it a natural fit."
      )
      .font(.callout)
      .foregroundStyle(Color.white.opacity(0.72))
      .fixedSize(horizontal: false, vertical: true)
      .frame(maxWidth: 470, alignment: .leading)
    }
  }

  private var gameSelector: some View {
    // macOS Menu extracts its native title from the label instead of rendering
    // an arbitrary SwiftUI hierarchy. Keep the title simple and style outside.
    Menu(model.selectedGame?.name ?? "Choose a game…") {
      ForEach(model.games) { game in
        Button(game.name) { model.selectedGame = game }
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
    .help("Choose an analyzed Game Profile")
  }

  @ViewBuilder private var submit: some View {
    if policy.showsSubmit {
      HStack(spacing: 8) {
        if model.isSubmitting {
          ProgressView()
            .controlSize(.small)
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

  @ViewBuilder private var gameLoadingAndFeedback: some View {
    if model.isLoadingGames {
      HStack(spacing: 8) {
        ProgressView()
          .controlSize(.small)
        Text("Loading Game Profiles…")
          .foregroundStyle(Color.white.opacity(0.75))
      }
    }

    if let gamesError = model.gamesError {
      HStack(spacing: 8) {
        Text(gamesError)
          .foregroundStyle(Color.white.opacity(0.8))
        Button("Try Again") {
          Task { await model.loadGames() }
        }
        .buttonStyle(.bordered)
      }
      .controlSize(.small)
    } else if !model.isLoadingGames && model.games.isEmpty {
      Label(
        "Add a Game Profile through Analyze Profile in Library to get started.",
        systemImage: "info.circle"
      )
      .foregroundStyle(Color.white.opacity(0.75))
      .font(.callout)
    }
  }

}
