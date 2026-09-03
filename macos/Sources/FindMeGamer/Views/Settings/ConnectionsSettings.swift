import FindMeGamerCore
import SwiftUI

struct ConnectionsSettings: View {
  @Bindable var model: SettingsModel

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var replacementConfirmation: ConnectionService?

  var body: some View {
    Section("Service Connections") {
      ForEach(model.connectionServices, id: \.self) { service in
        connectionRow(service)
      }
    }
    .confirmationDialog(
      "Replace \(replacementConfirmation?.displayName ?? "service") credential?",
      isPresented: confirmationPresented,
      titleVisibility: .visible
    ) {
      if let service = replacementConfirmation {
        Button("Replace Credential") {
          Task { await model.replaceConnection(service) }
        }
        Button("Cancel", role: .cancel) {}
      }
    } message: {
      Text("This shared connection change affects all coworkers in this Workspace.")
    }
  }

  private func connectionRow(_ service: ConnectionService) -> some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(alignment: .firstTextBaseline) {
        Text(service.displayName)
          .font(.headline)
        Spacer()
        if model.isLoadingConnection(service) || model.isConnectionActionInFlight(service) {
          ProgressView()
            .controlSize(.small)
        }
        Text(
          model.connectionStatus(for: service)?.configured == true ? "Configured" : "Not Configured"
        )
        .foregroundStyle(.secondary)
      }

      if let status = model.connectionStatus(for: service) {
        LabeledContent("Last Test", value: status.lastTestStatus.displayName)
        LabeledContent("Last Tested", value: formatted(status.lastTestedAt))
      } else if !model.isLoadingConnection(service) {
        Text("Connection status is unavailable.")
          .foregroundStyle(.secondary)
      }

      SecureField("Replacement credential", text: secretBinding(for: service))
        .textFieldStyle(.roundedBorder)
        .disabled(model.isConnectionActionInFlight(service))

      HStack {
        Button("Replace Credential") {
          replacementConfirmation = service
        }
        .disabled(
          !writesEnabled || model.isConnectionActionInFlight(service)
            || model.connectionSecret(for: service).trimmingCharacters(in: .whitespacesAndNewlines)
              .isEmpty
        )

        Button("Test Connection") {
          Task { await model.testConnection(service) }
        }
        .disabled(!writesEnabled || !model.canTestConnection(service))
      }

      if let error = model.connectionError(for: service) {
        Label(error, systemImage: "exclamationmark.triangle")
          .foregroundStyle(.red)
      }
    }
    .padding(.vertical, 4)
  }

  private func secretBinding(for service: ConnectionService) -> Binding<String> {
    Binding(
      get: { model.connectionSecret(for: service) },
      set: { model.updateConnectionSecret($0, for: service) })
  }

  private var confirmationPresented: Binding<Bool> {
    Binding(
      get: { replacementConfirmation != nil },
      set: { if !$0 { replacementConfirmation = nil } })
  }

  private func formatted(_ date: Date?) -> String {
    date?.formatted(date: .abbreviated, time: .shortened) ?? "Not available"
  }
}
