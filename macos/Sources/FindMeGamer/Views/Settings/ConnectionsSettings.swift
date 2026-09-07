import FindMeGamerCore
import SwiftUI

struct ConnectionsSettings: View {
  @Bindable var model: SettingsModel

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Bindable var presentation: SettingsPresentation

  var body: some View {
    Section("Service Connections") {
      ForEach(model.connectionServices, id: \.self) { service in
        InlineDisclosure(isExpanded: serviceExpanded(service)) {
          connectionRow(service)
        } label: {
          HStack(spacing: 12) {
            Text(service.displayName)
              .font(.headline)
            Spacer(minLength: 8)
            if model.isLoadingConnection(service) || model.isConnectionActionInFlight(service) {
              ProgressView().controlSize(.small)
            }
            Text(connectionSummary(service))
              .font(.subheadline)
              .foregroundStyle(
                model.connectionError(for: service) == nil ? Color.secondary : Color.red)
          }
          .padding(.vertical, 6)
        }
      }
    }
    .confirmationDialog(
      "Replace \(presentation.replacementConfirmation?.displayName ?? "service") credential?",
      isPresented: confirmationPresented,
      titleVisibility: .visible
    ) {
      if let service = presentation.replacementConfirmation {
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
      if let status = model.connectionStatus(for: service) {
        LabeledContent("Last Test", value: status.lastTestStatus.displayName)
        LabeledContent("Last Tested", value: formatted(status.lastTestedAt))
      } else if !model.isLoadingConnection(service) {
        Text("Connection status is unavailable.")
          .foregroundStyle(.secondary)
      }

      SecureField("Replacement \(service.credentialName)", text: secretBinding(for: service))
        .textFieldStyle(.roundedBorder)
        .disabled(model.isConnectionActionInFlight(service))

      Label("Workspace-shared credential", systemImage: "person.2")
        .font(.caption)
        .foregroundStyle(.secondary)

      HStack {
        Button("Replace Credential") {
          presentation.replacementConfirmation = service
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
        VStack(alignment: .leading, spacing: 8) {
          Label(error, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
          Button("Reload Status") {
            Task { await model.loadConnections() }
          }
          .disabled(model.isLoadingConnection(service))
        }
      }
    }
    .padding(.vertical, 4)
  }

  private func connectionSummary(_ service: ConnectionService) -> String {
    if model.connectionError(for: service) != nil { return "Needs attention" }
    if model.isLoadingConnection(service) { return "Checking…" }
    guard let status = model.connectionStatus(for: service) else { return "Unavailable" }
    return status.configured ? "Configured" : "Not Configured"
  }

  private func serviceExpanded(_ service: ConnectionService) -> Binding<Bool> {
    Binding(
      get: { presentation.expandedConnection == service },
      set: { presentation.expandedConnection = $0 ? service : nil })
  }

  private func secretBinding(for service: ConnectionService) -> Binding<String> {
    Binding(
      get: { model.connectionSecret(for: service) },
      set: { model.updateConnectionSecret($0, for: service) })
  }

  private var confirmationPresented: Binding<Bool> {
    Binding(
      get: { presentation.replacementConfirmation != nil },
      set: { if !$0 { presentation.replacementConfirmation = nil } })
  }

  private func formatted(_ date: Date?) -> String {
    date?.formatted(date: .abbreviated, time: .shortened) ?? "Not available"
  }
}
