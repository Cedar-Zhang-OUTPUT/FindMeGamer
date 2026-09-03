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

  private var presentation: CreatorCardPresentation { CreatorCardPresentation(card: card) }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Button(action: onOpen) {
        VStack(alignment: .leading, spacing: 8) {
          HStack(spacing: 10) {
            AsyncArtwork(url: presentation.artworkURL, fallbackSystemImage: "person.crop.circle")
              .frame(width: 58, height: 58)
              .clipShape(Circle())

            VStack(alignment: .leading, spacing: 3) {
              Text(presentation.name)
                .font(.headline)
                .lineLimit(2)
              subscriberLabel
                .font(.subheadline)
                .foregroundStyle(.secondary)
            }
          }

          Text(presentation.performanceSummary ?? "Performance summary unavailable.")
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .lineLimit(3)

          if !presentation.tags.isEmpty {
            LibraryTagRow(tags: presentation.tags)
          }

          Label("Contact: \(presentation.contactAvailability)", systemImage: "envelope")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open \(presentation.name)")
      .accessibilityIdentifier("library.profile.\(card.id.uuidString)")
      .help("Open this creator profile")

      HStack {
        Spacer()
        Button(action: onFavorite) {
          Image(systemName: presentation.isFavorite ? "heart.fill" : "heart")
            .foregroundStyle(presentation.isFavorite ? Color.accentColor : .secondary)
        }
        .buttonStyle(.borderless)
        .disabled(!writesEnabled || isUpdatingFavorite)
        .accessibilityLabel(
          presentation.isFavorite
            ? "Remove \(presentation.name) from favorites" : "Add \(presentation.name) to favorites"
        )
        .accessibilityIdentifier("library.favorite.\(card.id.uuidString)")
        .help(presentation.isFavorite ? "Remove from favorites" : "Add to favorites")
      }
    }
    .padding(12)
    .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10))
    .overlay {
      RoundedRectangle(cornerRadius: 10)
        .stroke(
          isHighlighted ? Color.accentColor : Color.secondary.opacity(0.18),
          lineWidth: isHighlighted ? 2 : 1)
    }
    .animation(.easeInOut(duration: 0.2), value: isHighlighted)
  }

  @ViewBuilder private var subscriberLabel: some View {
    if let subscriberCount = presentation.subscriberCount {
      Text(subscriberCount, format: .number) + Text(" subscribers")
    } else {
      Text("Subscribers unavailable.")
    }
  }
}
