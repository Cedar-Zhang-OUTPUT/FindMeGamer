import SwiftUI

/// A full-row disclosure with explicit state and native button keyboard behavior.
/// The owner retains the binding independently of the expandable content.
struct InlineDisclosure<Label: View, Content: View>: View {
  @Binding var isExpanded: Bool
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  private let label: Label
  private let content: Content

  init(
    _ title: String, isExpanded: Binding<Bool>, @ViewBuilder content: () -> Content
  ) where Label == Text {
    _isExpanded = isExpanded
    label = Text(title)
    self.content = content()
  }

  init(
    isExpanded: Binding<Bool>, @ViewBuilder content: () -> Content,
    @ViewBuilder label: () -> Label
  ) {
    _isExpanded = isExpanded
    self.label = label()
    self.content = content()
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Button {
        withAnimation(
          reduceMotion ? nil : WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: false)
        ) {
          isExpanded.toggle()
        }
      } label: {
        HStack(spacing: 8) {
          Image(systemName: "chevron.right")
            .font(.system(size: 10, weight: .semibold))
            .rotationEffect(.degrees(isExpanded ? 90 : 0))
            .accessibilityHidden(true)
          label
          Spacer(minLength: 0)
        }
        .frame(minHeight: 28)
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityValue(isExpanded ? "Expanded" : "Collapsed")

      if isExpanded {
        VStack(alignment: .leading, spacing: 12) {
          content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
      }
    }
  }
}
