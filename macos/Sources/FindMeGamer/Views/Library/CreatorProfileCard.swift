import FindMeGamerCore
import SwiftUI

struct CreatorCardPresentation: Equatable {
  let name: String
  let subscriberCount: Int?
  let audienceLabel: String
  let performanceSummary: String?
  let tags: [String]
  let artworkURL: URL?
  let contactAvailability: String
  let isFavorite: Bool

  init(card: FindMeGamerCore.CreatorProfileCard) {
    name = card.name
    let isX = CreatorPlatform.isX(url: card.canonicalURL)
    audienceLabel = isX ? "followers" : "subscribers"
    subscriberCount = LibraryJSON.count(
      card.currentFacts[isX ? "follower_count" : "subscriber_count"])
    performanceSummary = LibraryJSON.text(card.brief["performance_context"])
    tags = Array(LibraryJSON.strings(card.brief["content_focus"]).prefix(3))
    artworkURL = LibraryJSON.webURL(card.currentFacts["avatar_url"])
    contactAvailability = card.contactAvailability.displayName
    isFavorite = card.favorite
  }
}

struct CreatorProfileCard: View {
  let card: FindMeGamerCore.CreatorProfileCard
  let writesEnabled: Bool
  let isUpdatingFavorite: Bool
  let isHighlighted: Bool
  let onOpen: () -> Void
  let onFavorite: () -> Void

  @State private var isHovered = false
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  private var presentation: CreatorCardPresentation { CreatorCardPresentation(card: card) }
  private var identityColor: Color { StudioPalette.identityColor(for: card.id.uuidString) }

  var body: some View {
    WorkspaceSurface(style: .card) {
      Button(action: onOpen) {
        VStack(alignment: .leading, spacing: 0) {
          identityCover

          VStack(alignment: .leading, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
              Text(presentation.name)
                .font(.system(size: 20, weight: .semibold, design: .rounded))
                .tracking(-0.4)
                .foregroundStyle(StudioPalette.ink)
                .lineLimit(2)
              subscriberLabel
                .font(.caption.monospacedDigit())
                .foregroundStyle(.secondary)
            }

            if let summary = presentation.performanceSummary {
              Text(summary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineSpacing(2)
                .lineLimit(2)
            }

            if !presentation.tags.isEmpty {
              LibraryTagRow(tags: presentation.tags, tint: identityColor)
            }

            Spacer(minLength: 0)

            HStack {
              Label(
                presentation.contactAvailability == "Unavailable"
                  ? "No email yet" : "Email available",
                systemImage: "envelope"
              )
              .font(.caption).foregroundStyle(.secondary)
              Spacer()
              Image(systemName: "arrow.up.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(isHovered ? identityColor : Color.secondary)
                .frame(width: 25, height: 25)
                .background(identityColor.opacity(isHovered ? 0.14 : 0.06), in: Circle())
            }
          }
          .padding(16)
          .padding(.top, 2)
          .frame(maxWidth: .infinity, minHeight: 160, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open \(presentation.name)")
      .accessibilityValue(Text(accessibilitySummary))
      .accessibilityIdentifier("library.profile.\(card.id.uuidString)")
      .help("Open this creator profile")
    }
    .overlay {
      RoundedRectangle(cornerRadius: WorkspaceDesign.cardCornerRadius, style: .continuous)
        .stroke(
          isHighlighted ? Color.accentColor : Color.clear,
          lineWidth: isHighlighted ? 2 : 0
        )
        .allowsHitTesting(false)
    }
    .overlay(alignment: .topTrailing) {
      favoriteButton
        .padding(WorkspaceDesign.spaceS)
    }
    .shadow(color: identityColor.opacity(isHovered ? 0.14 : 0), radius: 16, y: 8)
    .offset(y: isHovered && !reduceMotion ? -3 : 0)
    .onHover { isHovered = $0 }
    .animation(
      WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
      value: isHovered
    )
    .animation(
      WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
      value: isHighlighted)
  }

  private var identityCover: some View {
    HStack(alignment: .bottom) {
      Group {
        if let url = presentation.artworkURL {
          AsyncArtwork(url: url, fallbackSystemImage: "person.crop.circle")
        } else {
          ZStack {
            Circle().fill(identityColor.opacity(0.18))
            Text(StudioPalette.initials(for: presentation.name))
              .font(.system(size: 23, weight: .semibold, design: .rounded))
              .foregroundStyle(StudioPalette.ink)
          }
        }
      }
      .frame(width: 62, height: 62)
      .clipShape(Circle())
      .padding(4)
      .background(StudioPalette.surface, in: Circle())

      Spacer()

    }
    .padding(.horizontal, 16)
    .padding(.bottom, 2)
    .frame(height: 94, alignment: .bottom)
    .background {
      LinearGradient(
        colors: [identityColor.opacity(0.22), identityColor.opacity(0.08), StudioPalette.surface],
        startPoint: .topLeading, endPoint: .bottomTrailing
      )
      .overlay(alignment: .trailing) {
        // Decoration must never determine the cover's size or displace the avatar.
        ZStack {
          Circle()
            .stroke(identityColor.opacity(0.18), lineWidth: 19)
            .frame(width: 144, height: 144)
          Circle()
            .stroke(identityColor.opacity(0.13), lineWidth: 1)
            .frame(width: 186, height: 186)
        }
        .offset(x: 44, y: -17)
      }
    }
    .clipShape(
      UnevenRoundedRectangle(
        topLeadingRadius: WorkspaceDesign.cardCornerRadius,
        topTrailingRadius: WorkspaceDesign.cardCornerRadius)
    )
    .accessibilityHidden(true)
  }

  private var favoriteButton: some View {
    Button(action: onFavorite) {
      Image(systemName: presentation.isFavorite ? "heart.fill" : "heart")
        .font(.callout.weight(.semibold))
        .foregroundStyle(
          presentation.isFavorite ? StudioPalette.coral : StudioPalette.ink.opacity(0.7)
        )
        .frame(width: 30, height: 30)
        .background(StudioPalette.surface.opacity(0.82), in: Circle())
    }
    .buttonStyle(.plain)
    .disabled(!writesEnabled || isUpdatingFavorite)
    .accessibilityLabel(
      presentation.isFavorite
        ? "Remove \(presentation.name) from favorites" : "Add \(presentation.name) to favorites"
    )
    .accessibilityIdentifier("library.favorite.\(card.id.uuidString)")
    .help(presentation.isFavorite ? "Remove from favorites" : "Add to favorites")
  }

  private var accessibilitySummary: String {
    var parts: [String] = []
    if let subscriberCount = presentation.subscriberCount {
      parts.append("\(subscriberCount.formatted()) \(presentation.audienceLabel)")
    }
    parts.append(presentation.performanceSummary ?? "Performance summary unavailable")
    if !presentation.tags.isEmpty {
      parts.append("Topics: \(presentation.tags.joined(separator: ", "))")
    }
    parts.append("Contact: \(presentation.contactAvailability)")
    if isHighlighted { parts.append("Recently updated") }
    return parts.joined(separator: " · ")
  }

  @ViewBuilder private var subscriberLabel: some View {
    if let subscriberCount = presentation.subscriberCount {
      Text(subscriberCount, format: .number) + Text(" \(presentation.audienceLabel)")
    } else {
      Text("\(presentation.audienceLabel.capitalized) —")
    }
  }
}
