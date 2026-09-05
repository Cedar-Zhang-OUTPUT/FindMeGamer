import SwiftUI

struct BatchOutreachBar: View {
  let selectedCount: Int
  let writesEnabled: Bool
  let actionState: MatchResultActionState
  let onSend: () -> Void
  var onRetry: () -> Void = {}
  var onClear: () -> Void = {}

  var body: some View {
    VStack(spacing: 0) {
      Rectangle().fill(StudioPalette.blue.opacity(0.18)).frame(height: 1)
      ViewThatFits(in: .horizontal) {
        HStack(spacing: 16) {
          summary
          Spacer(minLength: 8)
          actions
        }
        VStack(alignment: .leading, spacing: 12) {
          summary
          actions
        }
      }
      .fixedSize(horizontal: false, vertical: true)
      .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
      .padding(.vertical, 12)
      .frame(maxWidth: 1_040)
      .frame(maxWidth: .infinity)
    }
    .background(.regularMaterial)
  }

  private var summary: some View {
    HStack(spacing: 10) {
      if actionState == .refreshing {
        ProgressView().controlSize(.small)
      }
      if let status = actionState.statusLabel {
        VStack(alignment: .leading, spacing: 3) {
          Label(status, systemImage: actionState.showsRetry ? "arrow.clockwise" : "lock")
            .font(.callout.weight(.semibold))
          if actionState == .refreshRequired || actionState == .refreshing {
            Text("Saved result · outreach paused")
              .font(.caption).foregroundStyle(.secondary)
          }
        }
      } else {
        Label("\(selectedCount) selected", systemImage: "checkmark.circle.fill")
          .font(.callout.weight(.semibold))
          .foregroundStyle(StudioPalette.blue)
      }
    }
  }

  private var actions: some View {
    HStack(spacing: 12) {
      if actionState.showsRetry {
        Button("Retry", systemImage: "arrow.clockwise", action: onRetry)
          .buttonStyle(.bordered)
      }
      if selectedCount > 0 {
        Button("Clear", action: onClear)
          .buttonStyle(.borderless)
        Button("Compose for \(selectedCount)", systemImage: "arrow.right", action: onSend)
          .buttonStyle(.borderedProminent)
          .controlSize(.large)
          .disabled(!writesEnabled)
          .accessibilityIdentifier(MatchAccessibility.batchSend)
          .help("Review contacts and email previews before sending")
      }
    }
  }
}
