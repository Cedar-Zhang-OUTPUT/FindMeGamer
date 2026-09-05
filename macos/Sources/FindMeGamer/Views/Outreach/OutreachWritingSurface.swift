import SwiftUI

/// A quiet sheet of paper inside the studio, shared by draft and rendered-message views.
struct OutreachWritingSurface: ViewModifier {
  func body(content: Content) -> some View {
    content
      .background(StudioPalette.surface, in: RoundedRectangle(cornerRadius: 18))
      .overlay {
        RoundedRectangle(cornerRadius: 18)
          .strokeBorder(StudioPalette.ink.opacity(0.065), lineWidth: 1)
          .allowsHitTesting(false)
      }
      .shadow(color: .black.opacity(0.035), radius: 14, y: 6)
  }
}

struct OutreachDraftFieldStyle: TextFieldStyle {
  func _body(configuration: TextField<Self._Label>) -> some View {
    configuration
      .textFieldStyle(.plain)
      .padding(.horizontal, 12)
      .padding(.vertical, 10)
      .background(StudioPalette.surface, in: RoundedRectangle(cornerRadius: 10))
      .overlay {
        RoundedRectangle(cornerRadius: 10)
          .strokeBorder(StudioPalette.ink.opacity(0.12), lineWidth: 1)
          .allowsHitTesting(false)
      }
  }
}
