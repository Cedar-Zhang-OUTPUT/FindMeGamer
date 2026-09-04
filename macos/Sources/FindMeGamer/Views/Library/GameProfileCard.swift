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

  @State private var isHovered = false

  private var presentation: GameCardPresentation { GameCardPresentation(card: card) }

  var body: some View {
    WorkspaceSurface(style: isHovered || isHighlighted ? .elevated : .card) {
      Button(action: onOpen) {
        VStack(alignment: .leading, spacing: 0) {
          ZStack(alignment: .bottomLeading) {
            AsyncArtwork(url: presentation.artworkURL, fallbackSystemImage: "gamecontroller.fill")
              .frame(height: 154)

            LinearGradient(
              colors: [.clear, Color.black.opacity(0.5)],
              startPoint: .center,
              endPoint: .bottom)

            Text("GAME PROFILE")
              .font(.caption2.weight(.bold))
              .tracking(1.2)
              .foregroundStyle(.white.opacity(0.9))
              .padding(WorkspaceDesign.spaceS)
          }
          .clipShape(
            UnevenRoundedRectangle(
              topLeadingRadius: WorkspaceDesign.cardCornerRadius,
              topTrailingRadius: WorkspaceDesign.cardCornerRadius))

          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
            HStack(alignment: .firstTextBaseline, spacing: WorkspaceDesign.spaceS) {
              Text(presentation.name)
                .font(.title3.weight(.semibold))
                .lineLimit(2)
              Spacer(minLength: WorkspaceDesign.spaceS)
              Image(systemName: "arrow.up.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(isHovered ? Color.accentColor : .secondary)
            }

            Text(presentation.summary ?? "Summary unavailable.")
              .font(.callout)
              .foregroundStyle(.secondary)
              .lineLimit(3)

            Spacer(minLength: 0)

            if !presentation.tags.isEmpty {
              LibraryTagRow(tags: presentation.tags)
            }
          }
          .padding(14)
          .frame(maxWidth: .infinity, minHeight: 142, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open \(presentation.name)")
      .accessibilityValue(Text(accessibilitySummary))
      .accessibilityIdentifier("library.profile.\(card.id.uuidString)")
      .help("Open this game profile")
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
        .foregroundStyle(presentation.isFavorite ? Color.accentColor : .white.opacity(0.9))
        .frame(width: 30, height: 30)
        .background(.black.opacity(0.35), in: Circle())
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
    var parts = [presentation.summary ?? "Summary unavailable"]
    if !presentation.tags.isEmpty {
      parts.append("Tags: \(presentation.tags.joined(separator: ", "))")
    }
    if isHighlighted { parts.append("Recently updated") }
    return parts.joined(separator: " · ")
  }
}

struct LibraryTagRow: View {
  let tags: [String]

  var body: some View {
    HStack(spacing: WorkspaceDesign.spaceXS) {
      ForEach(tags, id: \.self) { tag in
        Text(tag)
          .font(.caption2.weight(.medium))
          .lineLimit(1)
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .background(Color.accentColor.opacity(0.09), in: Capsule())
      }
    }
  }
}
