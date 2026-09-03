import FindMeGamerCore
import SwiftUI

enum LibraryJSON {
  static func text(_ value: JSONValue?) -> String? {
    switch value {
    case .string(let value):
      let value = value.trimmingCharacters(in: .whitespacesAndNewlines)
      return value.isEmpty ? nil : value
    case .object(let object):
      return text(object["value"])
    default:
      return nil
    }
  }

  static func strings(_ value: JSONValue?) -> [String] {
    let values: [JSONValue]
    switch value {
    case .array(let array):
      values = array
    case .object(let object):
      guard case .array(let array) = object["values"] else { return [] }
      values = array
    default:
      return []
    }

    var seen = Set<String>()
    return values.compactMap { value in
      guard case .string(let rawString) = value else { return nil }
      let string = rawString.trimmingCharacters(in: .whitespacesAndNewlines)
      guard !string.isEmpty, seen.insert(string).inserted else { return nil }
      return string
    }
  }

  static func count(_ value: JSONValue?) -> Int? {
    switch value {
    case .integer(let value) where value >= 0:
      return value
    case .number(let value)
    where value.isFinite && value >= 0 && value.rounded(.towardZero) == value
      && value <= Double(Int.max):
      return Int(value)
    default:
      return nil
    }
  }

  static func webURL(_ value: JSONValue?) -> URL? {
    guard let string = text(value) else { return nil }
    return ArtworkURLPolicy.validated(URL(string: string))
  }
}

struct GameCardPresentation: Equatable {
  let name: String
  let summary: String?
  let tags: [String]
  let artworkURL: URL?
  let isFavorite: Bool

  init(card: FindMeGamerCore.GameProfileCard) {
    name = card.name
    summary =
      LibraryJSON.text(card.currentFacts["short_description"])
      ?? LibraryJSON.text(card.brief["positioning_premise"])
    let factTags = LibraryJSON.strings(card.currentFacts["genres"])
    let briefTags = LibraryJSON.strings(card.brief["genres"])
    tags = Array((factTags.isEmpty ? briefTags : factTags).prefix(3))
    artworkURL =
      LibraryJSON.webURL(card.currentFacts["cover_image_url"])
      ?? LibraryJSON.webURL(card.currentFacts["header_image_url"])
    isFavorite = card.favorite
  }
}

struct GameProfileCard: View {
  let card: FindMeGamerCore.GameProfileCard
  let writesEnabled: Bool
  let isUpdatingFavorite: Bool
  let isHighlighted: Bool
  let onOpen: () -> Void
  let onFavorite: () -> Void

  private var presentation: GameCardPresentation { GameCardPresentation(card: card) }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      Button(action: onOpen) {
        VStack(alignment: .leading, spacing: 10) {
          AsyncArtwork(url: presentation.artworkURL, fallbackSystemImage: "gamecontroller")
            .frame(height: 132)
            .clipShape(RoundedRectangle(cornerRadius: 8))

          Text(presentation.name)
            .font(.headline)
            .lineLimit(2)

          Text(presentation.summary ?? "Summary unavailable.")
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .lineLimit(3)

          if !presentation.tags.isEmpty {
            LibraryTagRow(tags: presentation.tags)
          }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open \(presentation.name)")
      .accessibilityIdentifier("library.profile.\(card.id.uuidString)")
      .help("Open this game profile")

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
}

struct LibraryTagRow: View {
  let tags: [String]

  var body: some View {
    HStack(spacing: 5) {
      ForEach(tags, id: \.self) { tag in
        Text(tag)
          .font(.caption)
          .lineLimit(1)
          .padding(.horizontal, 6)
          .padding(.vertical, 3)
          .background(Color.secondary.opacity(0.12), in: Capsule())
      }
    }
  }
}
