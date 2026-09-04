import FindMeGamerCore
import SwiftUI

struct SettingsView: View {
  @Bindable var model: SettingsModel

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
      WorkspacePageHeader(WorkspacePageCopy.settings) {
        WorkspaceStatusLozenge(
          title: model.workspaceStatus,
          systemImage: model.workspaceStatus == "Connected"
            ? "checkmark.circle.fill" : "wifi.slash",
          tone: model.workspaceStatus == "Connected" ? .success : .warning)
      }

      WorkspaceSurface(style: .card) {
        Form {
          AppearanceSettings(model: model)
          ConnectionsSettings(model: model)
          ReanalysisSettings(model: model)
          WorkspaceSettings(model: model)
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)
      }
      .frame(maxWidth: 980, maxHeight: .infinity, alignment: .topLeading)
    }
    .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
    .padding(.vertical, WorkspaceDesign.pageVerticalPadding)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .workspaceCanvas()
    .navigationTitle("Settings")
    .task {
      await model.loadConnections()
      await model.loadReanalysis()
      await model.loadProfileActivity()
    }
  }
}
