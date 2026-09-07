import FindMeGamerCore
import SwiftUI

struct WorkspaceSettings: View {
  @Bindable var model: SettingsModel

  @Bindable var presentation: SettingsPresentation

  var body: some View {
    Section("Workspace") {
      LabeledContent("Server Connection", value: model.workspaceStatus)

      InlineDisclosure("Connection details", isExpanded: $presentation.isShowingConnectionDetails) {
        LabeledContent(
          "Server URL", value: model.apiBaseURL.isEmpty ? "Not available" : model.apiBaseURL
        )
        .textSelection(.enabled)
        LabeledContent(
          "App version", value: model.appVersion.isEmpty ? "Development build" : model.appVersion)
      }
      .accessibilityIdentifier("settings.workspace.details")

      Button("Disconnect This Mac", role: .destructive) {
        presentation.isShowingDisconnectConfirmation = true
      }
      .disabled(model.isDisconnecting)
      .accessibilityIdentifier("settings.workspace.disconnect")

      if model.isDisconnecting {
        ProgressView("Disconnecting…")
      }
    }
    .confirmationDialog(
      "Disconnect This Mac?",
      isPresented: $presentation.isShowingDisconnectConfirmation,
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
