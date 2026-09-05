import SwiftUI

struct BatchOutreachBar: View {
  let selectedCount: Int
  let writesEnabled: Bool
  let isRefreshing: Bool
  let onSend: () -> Void

  var body: some View {
    VStack(spacing: 0) {
      LinearGradient(
        colors: [StudioPalette.blue.opacity(0.35), StudioPalette.mint.opacity(0.18), .clear],
        startPoint: .leading, endPoint: .trailing
      )
      .frame(height: 1)
      ViewThatFits(in: .horizontal) {
        HStack {
          summary
          Spacer()
          composeButton
        }
        VStack(alignment: .leading, spacing: 10) {
          summary
          composeButton
        }
      }
      .fixedSize(horizontal: false, vertical: true)
      .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
      .padding(.vertical, 14)
      .frame(maxWidth: 1_040, minHeight: 74)
      .frame(maxWidth: .infinity)
    }
    .background(.regularMaterial)
  }

  private var summary: some View {
    HStack(spacing: 12) {
      if selectedCount > 0 {
        Text(selectedCount, format: .number)
          .font(.system(size: 19, weight: .semibold, design: .rounded))
          .foregroundStyle(StudioPalette.blue)
          .frame(minWidth: 40, minHeight: 40)
          .background(StudioPalette.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 13))
          .accessibilityHidden(true)
      }
      VStack(alignment: .leading, spacing: 4) {
        Text(selectedCount > 0 ? "\(selectedCount) creators selected" : "Build your outreach list")
          .font(.system(.body, design: .rounded, weight: .semibold))
        Text(
          isRefreshing
            ? "Refreshing creator details…"
            : selectedCount > 0
              ? "You’ll review contacts and preview each email before sending."
              : "Select creators above, or compose an individual email."
        )
        .font(.caption)
        .foregroundStyle(.secondary)
      }
    }
  }

  private var composeButton: some View {
    Button("Compose outreach", systemImage: "arrow.right", action: onSend)
      .buttonStyle(.borderedProminent)
      .controlSize(.large)
      .disabled(selectedCount == 0 || !writesEnabled)
      .accessibilityIdentifier(MatchAccessibility.batchSend)
      .help("Compose Outreach for the selected Creators; no email is sent yet")
  }
}
