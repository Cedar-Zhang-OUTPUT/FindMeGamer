import AppKit
import SwiftUI

/// Brand color is decorative; it never encodes an inferred score or creator category.
enum StudioPalette {
  static let blue = adaptive(light: 0x315BE8, dark: 0x91ADFF)
  static let mint = adaptive(light: 0x167A69, dark: 0x6DDDC2)
  static let coral = adaptive(light: 0xB94C42, dark: 0xFF9D8F)
  static let amber = adaptive(light: 0x96600D, dark: 0xF1C773)
  static let ink = adaptive(light: 0x1D2940, dark: 0xEDF1FB)
  static let canvas = adaptive(light: 0xF7F8F6, dark: 0x111622)
  static let surface = adaptive(light: 0xFFFFFF, dark: 0x1B2333)
  static let line = adaptive(light: 0xDAE1EB, dark: 0x354155)

  static func identityIndex(for value: String) -> Int {
    let hash = value.utf8.reduce(UInt32(2_166_136_261)) { ($0 ^ UInt32($1)) &* 16_777_619 }
    return Int(hash % 4)
  }

  static func identityColor(for value: String) -> Color {
    [blue, mint, coral, amber][identityIndex(for: value)]
  }

  static func initials(for name: String) -> String {
    let words = name.split(whereSeparator: { $0.isWhitespace })
    let characters = words.prefix(2).compactMap(\.first)
    return characters.isEmpty ? "?" : String(characters).uppercased()
  }

  private static func adaptive(light: UInt32, dark: UInt32) -> Color {
    Color(
      nsColor: NSColor(name: nil) { appearance in
        let value = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
        return NSColor(
          srgbRed: CGFloat((value >> 16) & 0xFF) / 255,
          green: CGFloat((value >> 8) & 0xFF) / 255,
          blue: CGFloat(value & 0xFF) / 255,
          alpha: 1)
      })
  }
}

/// Original generated material, separate from all profile avatars and factual content.
enum StudioArtwork {
  static var coverURL: URL? {
    Bundle.main.url(forResource: "studio-orbit-cover", withExtension: "png")
      ?? Bundle.module.url(forResource: "studio-orbit-cover", withExtension: "png")
  }

  @MainActor static let coverImage = coverURL.flatMap { NSImage(contentsOf: $0) }
}

struct StudioCoverArt: View {
  @Environment(\.colorScheme) private var colorScheme

  var body: some View {
    GeometryReader { geometry in
      if let image = StudioArtwork.coverImage {
        Image(nsImage: image)
          .resizable()
          .scaledToFill()
          .frame(width: geometry.size.width, height: geometry.size.height)
          .clipped()
          .opacity(colorScheme == .dark ? 0.32 : 0.82)
      }
    }
    .accessibilityHidden(true)
    .allowsHitTesting(false)
  }
}

/// A short, local press response. No perpetual animation or pointer-only functionality.
struct StudioPressStyle: ButtonStyle {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  func makeBody(configuration: Configuration) -> some View {
    configuration.label
      .scaleEffect(configuration.isPressed && !reduceMotion ? 0.98 : 1)
      .opacity(configuration.isPressed ? 0.85 : 1)
      .animation(
        WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
        value: configuration.isPressed)
  }
}

/// All tabs remain keyboard-reachable; only the selected background moves.
struct StudioSectionTabs<Selection: Hashable>: View {
  let title: String
  let options: [Selection]
  @Binding var selection: Selection
  let label: (Selection) -> String

  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Namespace private var selectionNamespace

  var body: some View {
    HStack(spacing: 4) {
      ForEach(options, id: \.self) { option in
        Button {
          withAnimation(
            WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)
          ) {
            selection = option
          }
        } label: {
          Text(label(option))
            .font(.system(.subheadline, weight: selection == option ? .semibold : .medium))
            .foregroundStyle(selection == option ? StudioPalette.ink : .secondary)
            .padding(.horizontal, 14)
            .padding(.vertical, 9)
            .frame(maxWidth: .infinity)
            .background {
              if selection == option {
                if reduceMotion {
                  RoundedRectangle(cornerRadius: 10).fill(StudioPalette.surface)
                } else {
                  RoundedRectangle(cornerRadius: 10)
                    .fill(StudioPalette.surface)
                    .shadow(color: .black.opacity(0.06), radius: 4, y: 2)
                    .matchedGeometryEffect(id: "selection", in: selectionNamespace)
                }
              }
            }
            .contentShape(RoundedRectangle(cornerRadius: 10))
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selection == option ? .isSelected : [])
      }
    }
    .padding(4)
    .background(StudioPalette.ink.opacity(0.055), in: RoundedRectangle(cornerRadius: 14))
    .accessibilityElement(children: .contain)
    .accessibilityLabel(title)
  }
}
