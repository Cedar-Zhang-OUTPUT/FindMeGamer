import FindMeGamerCore
import SwiftUI

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

      if !session.message.isEmpty {
        Text(session.message)
          .font(.callout)
          .foregroundStyle(.secondary)
          .multilineTextAlignment(.center)
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
