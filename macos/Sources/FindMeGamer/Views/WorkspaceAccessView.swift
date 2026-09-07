import FindMeGamerCore
import SwiftUI

enum WorkspaceAccessFeedback {
  /// Controls already express the normal entry and connection states. Only
  /// omit these exact built-in hints; unfamiliar errors must remain visible.
  static func visibleMessage(state: AppSession.State, message: String) -> String? {
    guard !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }
    switch (state, message) {
    case (.needsKey, "Enter a Workspace Access Key to connect."),
      (.checking, "Checking workspace access…"),
      (.authenticated, "Connected."):
      return nil
    default:
      return message
    }
  }
}

struct WorkspaceAccessView: View {
  let session: AppSession

  @Binding var key: String
  @FocusState private var keyFieldIsFocused: Bool

  var body: some View {
    VStack(spacing: 18) {
      Text("Connect to Find Me Gamer")
        .font(.title2.weight(.semibold))

      Text("Workspace Access Key")
        .font(.subheadline.weight(.medium))
        .frame(maxWidth: .infinity, alignment: .leading)
      SecureField("Workspace Access Key", text: $key)
        .textFieldStyle(.roundedBorder)
        .focused($keyFieldIsFocused)
        .onSubmit(connect)
        .help("Use the Workspace Access Key provided by your team")

      if let message = WorkspaceAccessFeedback.visibleMessage(
        state: session.state, message: session.message)
      {
        Label(
          message, systemImage: session.state == .offline ? "wifi.slash" : "exclamationmark.circle"
        )
        .font(.callout)
        .foregroundStyle(.secondary)
        .multilineTextAlignment(.center)
        .fixedSize(horizontal: false, vertical: true)
        .textSelection(.enabled)
      }

      HStack {
        if session.state == .offline {
          Button("Try Again") {
            let candidate = key
            Task {
              await session.retryAccess(key: candidate)
              clearSavedCandidate()
            }
          }
        }

        Button(action: connect) {
          HStack(spacing: 6) {
            if session.state == .checking { ProgressView().controlSize(.mini) }
            Text(session.state == .checking ? "Connecting…" : "Connect")
          }
        }
        .buttonStyle(.borderedProminent)
        .keyboardShortcut(.defaultAction)
        .disabled(
          session.state == .checking
            || key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      }
    }
    .frame(maxWidth: 380)
    .padding(40)
    .onAppear { keyFieldIsFocused = true }
  }

  private func connect() {
    guard session.state != .checking,
      !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else { return }
    let candidate = key
    Task {
      await session.connect(key: candidate)
      clearSavedCandidate()
    }
  }

  private func clearSavedCandidate() {
    if session.service != nil {
      key = ""
    }
  }
}
