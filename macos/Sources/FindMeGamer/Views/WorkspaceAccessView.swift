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

      Text("Enter the Workspace Access Key provided by your team.")
        .foregroundStyle(.secondary)

      SecureField("Workspace Access Key", text: $key)
        .textFieldStyle(.roundedBorder)
        .focused($keyFieldIsFocused)
        .onSubmit(connect)

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

        Button("Connect", action: connect)
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
