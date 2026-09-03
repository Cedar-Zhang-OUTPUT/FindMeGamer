import FindMeGamerCore
import SwiftUI

struct WorkspaceSettings: View {
  @Bindable var model: SettingsModel

  @State private var isShowingDisconnectConfirmation = false

  var body: some View {
    Section("Workspace") {
      LabeledContent("Server Connection", value: model.workspaceStatus)
      LabeledContent(
        "API Base URL", value: model.apiBaseURL.isEmpty ? "Not available" : model.apiBaseURL)
      LabeledContent(
        "App Version", value: model.appVersion.isEmpty ? "Not available" : model.appVersion)

      Button("Disconnect This Mac", role: .destructive) {
        isShowingDisconnectConfirmation = true
      }
      .disabled(model.isDisconnecting)

      if model.isDisconnecting {
        ProgressView("Disconnecting…")
      }
    }
    .confirmationDialog(
      "Disconnect This Mac?",
      isPresented: $isShowingDisconnectConfirmation,
      titleVisibility: .visible
    ) {
      Button("Disconnect This Mac", role: .destructive) {
        Task { await model.disconnectThisMac() }
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("This clears only this Mac's Workspace Access Key. It does not change cloud data.")
    }
  }
}
