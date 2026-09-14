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
  var isCompact = false

  @State private var isShowingAnalysisDetails = false

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      identity
      if !isCompact { ProfileMetricStrip(metrics: sourceMetrics) }
    }
    .padding(isCompact ? 12 : 16)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background {
      ZStack(alignment: .trailing) {
        RoundedRectangle(cornerRadius: 24).fill(StudioPalette.surface)
        StudioCoverArt()
          .opacity(0.48)
          .mask(
            LinearGradient(
              colors: [.clear, .black.opacity(0.2), .black], startPoint: .leading,
              endPoint: .trailing))
      }
      .clipShape(RoundedRectangle(cornerRadius: 24))
      .accessibilityHidden(true)
    }
    .overlay {
      RoundedRectangle(cornerRadius: 24)
        .strokeBorder(StudioPalette.blue.opacity(0.08), lineWidth: 1)
    }
    .fixedSize(horizontal: false, vertical: true)
  }

  private var identity: some View {
    HStack(alignment: .center, spacing: 14) {
      identityArtwork

      VStack(alignment: .leading, spacing: 7) {
        VStack(alignment: .leading, spacing: 5) {
          Text(name)
            .font(.system(size: isCompact ? 21 : 25, weight: .bold, design: .rounded))
            .tracking(-0.75)
            .foregroundStyle(StudioPalette.ink)
            .fixedSize(horizontal: false, vertical: true)
            .textSelection(.enabled)
            .accessibilityAddTraits(.isHeader)
        }

        ViewThatFits(in: .horizontal) {
          HStack(spacing: 10) {
            sourceLink
            actions
          }
          VStack(alignment: .leading, spacing: 8) {
            sourceLink
            actions
          }
        }
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
  }

  private var actions: some View {
    HStack(spacing: 8) {
      Button(action: onFavorite) {
        Label(
          isFavorite ? "Favorited" : "Favorite",
          systemImage: isFavorite ? "heart.fill" : "heart")
      }
      .tint(isFavorite ? StudioPalette.coral : StudioPalette.blue)
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
      Button("Analysis Details") { isShowingAnalysisDetails.toggle() }
        .buttonStyle(.borderless)
        .popover(isPresented: $isShowingAnalysisDetails) {
          analysisSchedule.padding(16)
        }
        .accessibilityIdentifier("profile.analysisDetails")
    }
    .controlSize(.small)
  }

  private var analysisSchedule: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 14) {
        analyzedLabel
        refreshLabel
      }
      VStack(alignment: .leading, spacing: 4) {
        analyzedLabel
        refreshLabel
      }
    }
    .font(.caption)
    .foregroundStyle(.secondary)
    .textSelection(.enabled)
  }

  private var analyzedLabel: some View {
    Label("Analyzed \(dateText(lastAnalyzedAt))", systemImage: "clock.arrow.circlepath")
  }

  private var refreshLabel: some View {
    Label("Next refresh \(dateText(nextAnalysisAt))", systemImage: "calendar.badge.clock")
  }

  private var sourceLink: some View {
    Group {
      if let sourceURL {
        Link(destination: sourceURL) {
          Label(sourceLinkLabel, systemImage: "arrow.up.right")
            .font(.caption.weight(.medium))
        }
        .help("Open the canonical source page")
      } else {
        Label("Source link unavailable", systemImage: "link.badge.plus")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
    }
    .accessibilityIdentifier("profile.source")
  }

  private var identityArtwork: some View {
    Group {
      if type == .creator {
        ZStack {
          Circle().stroke(identityColor.opacity(0.18), lineWidth: 1)
          artworkContent
            .frame(width: isCompact ? 40 : 60, height: isCompact ? 40 : 60)
            .clipShape(Circle())
          Circle()
            .fill(StudioPalette.surface)
            .frame(width: 21, height: 21)
            .overlay {
              Image(systemName: "play.fill")
                .font(.system(size: 8, weight: .bold))
                .foregroundStyle(identityColor)
            }
            .offset(x: isCompact ? 17 : 25, y: isCompact ? 17 : 25)
        }
        .frame(width: isCompact ? 48 : 68, height: isCompact ? 48 : 68)
      } else {
        artworkContent
          .frame(width: isCompact ? 56 : 82, height: isCompact ? 48 : 66)
          .clipShape(RoundedRectangle(cornerRadius: 18))
          .rotationEffect(.degrees(-3))
          .overlay {
            RoundedRectangle(cornerRadius: 18)
              .strokeBorder(.white.opacity(0.25), lineWidth: 1)
              .rotationEffect(.degrees(-3))
          }
      }
    }
    .accessibilityHidden(true)
  }

  private var artworkContent: some View {
    Group {
      if let artworkURL {
        AsyncArtwork(url: artworkURL, fallbackSystemImage: fallbackSystemImage)
      } else {
        ZStack {
          LinearGradient(
            colors: [identityColor.opacity(0.2), identityColor.opacity(0.07)],
            startPoint: .topLeading, endPoint: .bottomTrailing)
          Text(StudioPalette.initials(for: name))
            .font(.system(size: 25, weight: .bold, design: .rounded))
            .foregroundStyle(identityColor)
        }
      }
    }
  }

  private var identityColor: Color {
    StudioPalette.identityColor(for: name)
  }

  private var sourceMetrics: [ProfileMetricPresentation] {
    switch profile {
    case .game(let game):
      ProfileMetricPresentation.sourceMetrics(
        fields: GameProfilePresentation(profile: game).sourceFacts, type: .game)
    case .creator(let creator):
      ProfileMetricPresentation.sourceMetrics(
        fields: CreatorProfilePresentation(profile: creator).sourceFacts, type: .creator)
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
    switch profile {
    case .game: "Steam"
    case .creator(let creator): CreatorPlatform.isX(url: creator.canonicalURL) ? "X" : "YouTube"
    }
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
