import FindMeGamerCore
import SwiftUI

struct ProfileHeader: View {
  let profile: Profile
  let isFavorite: Bool
  let writesEnabled: Bool
  let isFavoriteInFlight: Bool
  let isReanalyzeInFlight: Bool
  let onFavorite: () -> Void
  let onReanalyze: () -> Void

  var body: some View {
    HStack(alignment: .top, spacing: 18) {
      AsyncArtwork(url: artworkURL, fallbackSystemImage: fallbackSystemImage)
        .frame(width: 112, height: 112)
        .clipShape(RoundedRectangle(cornerRadius: 10))

      VStack(alignment: .leading, spacing: 8) {
        Text(name)
          .font(.title2.weight(.semibold))
          .textSelection(.enabled)
        Text(type.displayName)
          .font(.subheadline)
          .foregroundStyle(.secondary)

        if let sourceURL {
          Link(destination: sourceURL) {
            Label(sourceLinkLabel, systemImage: "arrow.up.right.square")
          }
          .accessibilityIdentifier("profile.source")
          .help("Open the canonical source page")
        } else {
          Label("Source link unavailable", systemImage: "link.badge.plus")
            .foregroundStyle(.secondary)
            .accessibilityIdentifier("profile.source")
        }

        HStack(spacing: 10) {
          Button(action: onFavorite) {
            Label(
              isFavorite ? "Favorited" : "Favorite",
              systemImage: isFavorite ? "heart.fill" : "heart")
          }
          .disabled(
            !ProfileActionPolicy.canFavorite(
              writesEnabled: writesEnabled, isInFlight: isFavoriteInFlight)
          )
          .accessibilityIdentifier("profile.favorite")
          .help(isFavorite ? "Remove from favorites" : "Add to favorites")

          Button(action: onReanalyze) {
            Label("Re-analyze", systemImage: "arrow.clockwise")
          }
          .disabled(
            !ProfileActionPolicy.canReanalyze(
              writesEnabled: writesEnabled, isInFlight: isReanalyzeInFlight)
          )
          .accessibilityIdentifier("profile.reanalyze")
          .help("Request fresh profile analysis")

          if isFavoriteInFlight || isReanalyzeInFlight {
            ProgressView()
              .controlSize(.small)
          }
        }
      }

      Spacer(minLength: 12)

      Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 7) {
        GridRow {
          Text("Last Analyzed")
            .foregroundStyle(.secondary)
          Text(dateText(lastAnalyzedAt))
            .textSelection(.enabled)
        }
        GridRow {
          Text("Next Re-analysis")
            .foregroundStyle(.secondary)
          Text(dateText(nextAnalysisAt))
            .textSelection(.enabled)
        }
      }
      .font(.subheadline)
    }
  }

  private var type: ProfileType {
    switch profile {
    case .game: .game
    case .creator: .creator
    }
  }

  private var name: String {
    switch profile {
    case .game(let game): game.name
    case .creator(let creator): creator.name
    }
  }

  private var sourceURL: URL? {
    switch profile {
    case .game(let game): ProfileLinkPolicy.validated(game.canonicalURL)
    case .creator(let creator): ProfileLinkPolicy.validated(creator.canonicalURL)
    }
  }

  private var artworkURL: URL? {
    switch profile {
    case .game(let game): GameProfilePresentation(profile: game).artworkURL
    case .creator(let creator): CreatorProfilePresentation(profile: creator).artworkURL
    }
  }

  private var fallbackSystemImage: String {
    type == .game ? "gamecontroller" : "person.crop.circle"
  }

  private var sourceLinkLabel: String {
    type == .game ? "Open on Steam" : "Open on YouTube"
  }

  private var lastAnalyzedAt: Date? {
    switch profile {
    case .game(let game): game.lastAnalyzedAt
    case .creator(let creator): creator.lastAnalyzedAt
    }
  }

  private var nextAnalysisAt: Date? {
    switch profile {
    case .game(let game): game.nextAnalysisAt
    case .creator(let creator): creator.nextAnalysisAt
    }
  }

  private func dateText(_ date: Date?) -> String {
    date?.formatted(date: .abbreviated, time: .shortened) ?? "Not available"
  }
}
