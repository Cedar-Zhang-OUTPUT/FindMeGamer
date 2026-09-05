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
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  private var presentation: GameCardPresentation { GameCardPresentation(card: card) }
  private var identityColor: Color { StudioPalette.identityColor(for: card.id.uuidString) }

  var body: some View {
    WorkspaceSurface(style: .card) {
      Button(action: onOpen) {
        VStack(alignment: .leading, spacing: 0) {
          VStack(alignment: .leading, spacing: 6) {
            Text(presentation.name)
              .font(.system(size: 23, weight: .semibold, design: .rounded))
              .tracking(-0.5)
              .foregroundStyle(.white)
              .lineLimit(2)
              .shadow(color: .black.opacity(0.2), radius: 3, y: 1)
          }
          .padding(17)
          .frame(maxWidth: .infinity, alignment: .leading)
          .frame(height: 162, alignment: .bottomLeading)
          .background {
            // Keep artwork and oversized ornaments out of the title's layout measurement.
            Group {
              if let url = presentation.artworkURL {
                AsyncArtwork(url: url, fallbackSystemImage: "gamecontroller.fill")
              } else {
                LinearGradient(
                  colors: [identityColor, Color(red: 0.09, green: 0.12, blue: 0.23)],
                  startPoint: .topLeading, endPoint: .bottomTrailing
                )
                .overlay(alignment: .topTrailing) {
                  Image(systemName: "gamecontroller")
                    .font(.system(size: 92, weight: .ultraLight))
                    .rotationEffect(.degrees(-18))
                    .foregroundStyle(.white.opacity(0.18))
                    .offset(x: 16, y: 22)
                }
              }
            }
            .overlay {
              LinearGradient(
                colors: [.black.opacity(0.06), Color.black.opacity(0.76)],
                startPoint: .top, endPoint: .bottom)
            }
          }
          .clipShape(
            UnevenRoundedRectangle(
              topLeadingRadius: WorkspaceDesign.cardCornerRadius,
              topTrailingRadius: WorkspaceDesign.cardCornerRadius))

          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
            if let summary = presentation.summary {
              Text(summary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineSpacing(2)
                .lineLimit(3)
            }

            Spacer(minLength: 0)

            HStack(alignment: .center, spacing: 8) {
              if !presentation.tags.isEmpty {
                LibraryTagRow(tags: presentation.tags, tint: identityColor)
              }
              Spacer(minLength: 0)
              Image(systemName: "arrow.up.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(isHovered ? identityColor : Color.secondary)
                .frame(width: 25, height: 25)
                .background(identityColor.opacity(isHovered ? 0.14 : 0.06), in: Circle())
            }
          }
          .padding(16)
          .frame(maxWidth: .infinity, minHeight: 132, alignment: .topLeading)
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
    .shadow(color: identityColor.opacity(isHovered ? 0.16 : 0), radius: 16, y: 8)
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

  private var favoriteButton: some View {
    Button(action: onFavorite) {
      Image(systemName: presentation.isFavorite ? "heart.fill" : "heart")
        .font(.callout.weight(.semibold))
        .foregroundStyle(presentation.isFavorite ? StudioPalette.coral : .white.opacity(0.95))
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
  var tint: Color = .secondary

  var body: some View {
    HStack(spacing: WorkspaceDesign.spaceXS) {
      ForEach(tags, id: \.self) { tag in
        Text(tag)
          .font(.caption2.weight(.medium))
          .lineLimit(1)
          .padding(.horizontal, 8)
          .padding(.vertical, 4)
          .foregroundStyle(StudioPalette.ink.opacity(0.8))
          .background(tint.opacity(0.085), in: Capsule())
      }
    }
  }
}
