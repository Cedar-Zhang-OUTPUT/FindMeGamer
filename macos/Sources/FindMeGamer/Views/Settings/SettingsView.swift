import FindMeGamerCore
import SwiftUI

struct SettingsView: View {
  @Bindable var model: SettingsModel

  var body: some View {
    Form {
      AppearanceSettings(model: model)
      ConnectionsSettings(model: model)
      ReanalysisSettings(model: model)
      WorkspaceSettings(model: model)
    }
    .formStyle(.grouped)
    .navigationTitle("Settings")
    .task {
      await model.loadConnections()
      await model.loadReanalysis()
      await model.loadProfileActivity()
    }
  }
}
