import FindMeGamerCore
import SwiftUI

struct CreatorCardPresentation: Equatable {
  let name: String
  let subscriberCount: Int?
  let performanceSummary: String?
  let tags: [String]
  let artworkURL: URL?
  let contactAvailability: String
  let isFavorite: Bool

  init(card: FindMeGamerCore.CreatorProfileCard) {
    name = card.name
    subscriberCount = LibraryJSON.count(card.currentFacts["subscriber_count"])
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

  private var presentation: CreatorCardPresentation { CreatorCardPresentation(card: card) }

  var body: some View {
    WorkspaceSurface(style: isHovered || isHighlighted ? .elevated : .card) {
      Button(action: onOpen) {
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
          HStack(alignment: .top, spacing: 13) {
            AsyncArtwork(url: presentation.artworkURL, fallbackSystemImage: "person.crop.circle")
              .frame(width: 72, height: 72)
              .clipShape(Circle())
              .overlay {
                Circle().strokeBorder(Color.primary.opacity(0.1))
              }

            VStack(alignment: .leading, spacing: 5) {
              Text(presentation.name)
                .font(.title3.weight(.semibold))
                .lineLimit(2)
              subscriberLabel
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)

              WorkspaceStatusLozenge(
                title: presentation.contactAvailability,
                systemImage: "envelope.fill",
                tone: presentation.contactAvailability == "Unavailable" ? .neutral : .success)
            }

            Spacer(minLength: 28)
          }

          Text(presentation.performanceSummary ?? "Performance summary unavailable.")
            .font(.callout)
            .foregroundStyle(.secondary)
            .lineLimit(2)

          Spacer(minLength: 0)

          if !presentation.tags.isEmpty {
            LibraryTagRow(tags: presentation.tags)
          }

          Label("Open creator profile", systemImage: "arrow.up.right")
            .font(.caption)
            .foregroundStyle(isHovered ? Color.accentColor : .secondary)
        }
        .padding(WorkspaceDesign.spaceM)
        .frame(maxWidth: .infinity, minHeight: 244, alignment: .topLeading)
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
    .onHover { isHovered = $0 }
    .animation(.easeOut(duration: 0.18), value: isHovered)
    .animation(.easeInOut(duration: 0.2), value: isHighlighted)
  }

  private var favoriteButton: some View {
    Button(action: onFavorite) {
      Image(systemName: presentation.isFavorite ? "heart.fill" : "heart")
        .font(.callout.weight(.semibold))
        .foregroundStyle(presentation.isFavorite ? Color.accentColor : .secondary)
        .frame(width: 30, height: 30)
        .background(Color.primary.opacity(0.055), in: Circle())
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
      parts.append("\(subscriberCount.formatted()) subscribers")
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
      Text(subscriberCount, format: .number) + Text(" subscribers")
    } else {
      Text("Subscribers unavailable.")
    }
  }
}
