import SwiftUI

struct OfflineBanner: View {
  let retry: () -> Void

  var body: some View {
    VStack(spacing: 0) {
      HStack {
        Label("Offline — changes are unavailable.", systemImage: "wifi.slash")
          .foregroundStyle(.secondary)

        Spacer()

        Button("Retry", action: retry)
      }
      .padding(.horizontal)
      .padding(.vertical, 10)

      Divider()
    }
  }
}
