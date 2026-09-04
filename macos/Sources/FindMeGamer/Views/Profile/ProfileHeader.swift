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
    ViewThatFits(in: .horizontal) {
      HStack(alignment: .top, spacing: WorkspaceDesign.spaceL) {
        identity
        Spacer(minLength: WorkspaceDesign.spaceL)
        analysisSchedule
      }

      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        identity
        analysisSchedule
      }
    }
  }

  private var identity: some View {
    HStack(alignment: .top, spacing: WorkspaceDesign.spaceM) {
      AsyncArtwork(url: artworkURL, fallbackSystemImage: fallbackSystemImage)
        .frame(width: 124, height: 104)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))

      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
        VStack(alignment: .leading, spacing: 4) {
          WorkspaceStatusLozenge(
            title: "\(type.displayName) Profile",
            systemImage: type == .game ? "gamecontroller.fill" : "person.crop.circle.fill",
            tone: .accent)

          Text(name)
            .font(.system(.title, design: .serif, weight: .semibold))
            .textSelection(.enabled)
            .accessibilityAddTraits(.isHeader)
        }

        if let sourceURL {
          Link(destination: sourceURL) {
            Label(sourceLinkLabel, systemImage: "arrow.up.right")
          }
          .accessibilityIdentifier("profile.source")
          .help("Open the canonical source page")
        } else {
          Label("Source link unavailable", systemImage: "link.badge.plus")
            .foregroundStyle(.secondary)
            .accessibilityIdentifier("profile.source")
        }

        HStack(spacing: WorkspaceDesign.spaceS) {
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
              .accessibilityLabel("Updating Profile")
          }
        }
      }
    }
  }

  private var analysisSchedule: some View {
    WorkspaceSurface(style: .quiet) {
      Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 7) {
        GridRow {
          Label("Last analyzed", systemImage: "clock.arrow.circlepath")
            .foregroundStyle(.secondary)
          Text(dateText(lastAnalyzedAt))
            .textSelection(.enabled)
        }
        GridRow {
          Label("Next refresh", systemImage: "calendar.badge.clock")
            .foregroundStyle(.secondary)
          Text(dateText(nextAnalysisAt))
            .textSelection(.enabled)
        }
      }
      .font(.subheadline)
      .padding(WorkspaceDesign.spaceS)
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
