import SwiftUI

/// A deliberately light control inside the fixed ink hero. Both the custom
/// SwiftUI label and AppKit's native menu fallback have a contrasting surface.
enum MatchInkControlColors {
  static let surface = Color(red: 0.95, green: 0.97, blue: 0.99)
  static let text = Color(red: 0.1, green: 0.16, blue: 0.24)
  static let secondaryText = Color(red: 0.34, green: 0.4, blue: 0.48)
  // Unlike the adaptive blue text token, this fill remains deep blue in the
  // local dark environment. White label contrast is 6.64:1 in sRGB.
  static let actionBackground = Color(red: 0.16, green: 0.32, blue: 0.8)
}

/// The illustration is a metaphor for connecting a game with creators, not match data.
struct MatchConnectionArtwork: View {
  var width: CGFloat = 144

  var body: some View {
    ZStack {
      Circle()
        .fill(Color.cyan.opacity(0.1))
        .frame(width: 150, height: 150)
        .blur(radius: 24)
      Ellipse()
        .strokeBorder(Color.white.opacity(0.16), lineWidth: 1)
        .frame(width: 198, height: 106)
        .rotationEffect(.degrees(-28))
      Ellipse()
        .strokeBorder(Color.white.opacity(0.08), style: StrokeStyle(lineWidth: 1, dash: [3, 6]))
        .frame(width: 168, height: 156)
        .rotationEffect(.degrees(24))

      Image(systemName: "gamecontroller.fill")
        .font(.system(size: 28, weight: .medium))
        .foregroundStyle(Color.white)
        .frame(width: 72, height: 72)
        .background(
          LinearGradient(
            colors: [
              Color(red: 0.25, green: 0.49, blue: 0.98), Color(red: 0.16, green: 0.28, blue: 0.6),
            ],
            startPoint: .topLeading, endPoint: .bottomTrailing),
          in: RoundedRectangle(cornerRadius: 24, style: .continuous)
        )
        .overlay {
          RoundedRectangle(cornerRadius: 24).strokeBorder(Color.white.opacity(0.24))
        }
        .rotationEffect(.degrees(-8))
        .shadow(color: .black.opacity(0.15), radius: 15, y: 10)

      node("person.fill", color: Color(red: 0.58, green: 0.92, blue: 0.79), size: 43)
        .offset(x: 79, y: -58)
      node("play.fill", color: Color(red: 1, green: 0.68, blue: 0.59), size: 35)
        .offset(x: -82, y: 45)
      node("mic.fill", color: Color(red: 0.74, green: 0.77, blue: 1), size: 30)
        .offset(x: 66, y: 57)
      Circle().fill(Color.white.opacity(0.65)).frame(width: 5, height: 5)
        .offset(x: -65, y: -63)
    }
    .frame(width: 224, height: 186)
    .scaleEffect(width / 224)
    .frame(width: width, height: width * 186 / 224)
    .accessibilityHidden(true)
    .allowsHitTesting(false)
  }

  private func node(_ symbol: String, color: Color, size: CGFloat) -> some View {
    Image(systemName: symbol)
      .font(.system(size: size * 0.36, weight: .semibold))
      .foregroundStyle(Color(red: 0.1, green: 0.17, blue: 0.22))
      .frame(width: size, height: size)
      .background(color.gradient, in: Circle())
      .overlay { Circle().strokeBorder(Color.white.opacity(0.6), lineWidth: 1) }
      .shadow(color: .black.opacity(0.12), radius: 8, y: 4)
  }
}

struct MatchInkSurface: ViewModifier {
  func body(content: Content) -> some View {
    content
      .foregroundStyle(.white)
      // This panel is always ink, independent of the workspace appearance.
      // Native progress indicators and button chrome must share that context.
      .environment(\.colorScheme, .dark)
      .background {
        RoundedRectangle(cornerRadius: 26, style: .continuous)
          .fill(
            LinearGradient(
              colors: [
                Color(red: 0.12, green: 0.18, blue: 0.27),
                Color(red: 0.07, green: 0.11, blue: 0.18),
              ],
              startPoint: .topLeading, endPoint: .bottomTrailing)
          )
          .overlay {
            RoundedRectangle(cornerRadius: 26, style: .continuous)
              .strokeBorder(Color.white.opacity(0.1))
          }
      }
      .shadow(color: Color.black.opacity(0.1), radius: 18, y: 8)
  }
}

enum MatchEvidenceCategory: String, CaseIterable, Identifiable {
  case content, audience, performance, promotion, safety

  var id: String { rawValue }

  var title: String {
    switch self {
    case .content: "Content Fit"
    case .audience: "Audience Fit"
    case .performance: "Performance Fit"
    case .promotion: "Promotion Fit"
    case .safety: "Brand Safety"
    }
  }

  var symbol: String {
    switch self {
    case .content: "play.rectangle"
    case .audience: "person.2"
    case .performance: "chart.line.uptrend.xyaxis"
    case .promotion: "megaphone"
    case .safety: "checkmark.shield"
    }
  }

  var color: Color {
    switch self {
    case .content: StudioPalette.blue
    case .audience: StudioPalette.mint
    case .performance: StudioPalette.coral
    case .promotion: StudioPalette.amber
    case .safety: StudioPalette.blue
    }
  }
}
