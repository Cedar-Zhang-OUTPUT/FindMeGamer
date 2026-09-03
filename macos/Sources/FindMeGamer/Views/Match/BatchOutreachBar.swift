import SwiftUI

struct BatchOutreachBar: View {
  let selectedCount: Int
  let writesEnabled: Bool
  let onSend: () -> Void

  var body: some View {
    if selectedCount > 0 {
      AdaptiveGlassSurface(role: .batchOutreach) {
        HStack {
          Text("\(selectedCount) selected")
            .foregroundStyle(.secondary)
          Spacer()
          Button(MatchCopy.sendOutreach(count: selectedCount), action: onSend)
            .buttonStyle(.borderedProminent)
            .disabled(!writesEnabled)
            .accessibilityIdentifier(MatchAccessibility.batchSend)
            .help("Compose Outreach for the selected Creators")
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
      }
    }
  }
}
