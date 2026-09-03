import FindMeGamerCore
import SwiftUI

struct EmailSettingsView: View {
  @Bindable var model: SettingsModel

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var confirmation: Confirmation?

  var body: some View {
    Form {
      Section("Email Settings") {
        if model.isLoadingSMTP && model.smtpStatus == nil {
          ProgressView("Loading Email Settings…")
        }

        LabeledContent(
          "Mailbox", value: model.smtpStatus?.configured == true ? "Configured" : "Not Configured")

        TextField("Host", text: host)
          .textFieldStyle(.roundedBorder)
        TextField("Port", value: port, format: .number)
          .textFieldStyle(.roundedBorder)
        Picker("Encryption", selection: encryption) {
          Text("Select").tag(nil as SMTPEncryption?)
          ForEach(SMTPEncryption.allCases, id: \.self) { option in
            Text(option.displayName).tag(option as SMTPEncryption?)
          }
        }
        TextField("Username", text: username)
          .textFieldStyle(.roundedBorder)
        SecureField(
          model.smtpStatus?.configured == true ? "Replacement password (optional)" : "Password",
          text: password
        )
        .textFieldStyle(.roundedBorder)
        TextField("From Name", text: fromName)
          .textFieldStyle(.roundedBorder)
        TextField("Reply-To", text: replyTo)
          .textFieldStyle(.roundedBorder)
        TextField("Emails per minute", value: emailsPerMinute, format: .number)
          .textFieldStyle(.roundedBorder)

        if let status = model.smtpStatus {
          LabeledContent("Last Test", value: status.lastTestStatus.displayName)
          LabeledContent("Last Tested", value: formatted(status.lastTestedAt))
        }

        HStack {
          Button("Save Email Settings") {
            confirmation = .save
          }
          .disabled(!writesEnabled || !model.canSaveSMTP)

          Button("Test Connection") {
            Task { await model.testSMTPConnection() }
          }
          .disabled(!writesEnabled || !model.canTestSMTP)

          if smtpActionInFlight {
            ProgressView()
              .controlSize(.small)
          }
        }

        if model.smtpStatus?.configured == true && model.smtpIsDirty {
          Text("Save Email Settings before testing the connection or sending a test email.")
            .foregroundStyle(.secondary)
        }

        Divider()

        TextField("Company test recipient", text: testRecipient)
          .textFieldStyle(.roundedBorder)
          .disabled(model.isSendingSMTPTest)
        Button("Send Test Email") {
          confirmation = .sendTest
        }
        .disabled(!writesEnabled || !model.canSendSMTPTest)

        if let error = model.smtpLoadError {
          HStack {
            Label(error, systemImage: "exclamationmark.triangle")
              .foregroundStyle(.red)
            Spacer()
            Button("Try Again") {
              Task { await model.loadSMTPSettings() }
            }
            .disabled(model.isLoadingSMTP)
          }
        }

        if let error = model.smtpActionError {
          Label(error, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
        }
      }
      .disabled(smtpActionInFlight)
    }
    .formStyle(.grouped)
    .navigationTitle("Email Settings")
    .task { await model.loadSMTPSettings() }
    .confirmationDialog(
      confirmation?.title ?? "Confirm Email Settings action",
      isPresented: confirmationPresented,
      titleVisibility: .visible
    ) {
      if let confirmation {
        Button(confirmation.buttonTitle) {
          perform(confirmation)
        }
        Button("Cancel", role: .cancel) {}
      }
    } message: {
      if let confirmation {
        Text(confirmation.message)
      }
    }
  }

  private var smtpActionInFlight: Bool {
    model.isSavingSMTP || model.isTestingSMTP || model.isSendingSMTPTest
  }

  private var host: Binding<String> { smtpBinding(\.host) }
  private var port: Binding<Int> { smtpBinding(\.port) }
  private var encryption: Binding<SMTPEncryption?> { smtpBinding(\.encryption) }
  private var username: Binding<String> { smtpBinding(\.username) }
  private var fromName: Binding<String> { smtpBinding(\.fromName) }
  private var replyTo: Binding<String> { smtpBinding(\.replyTo) }
  private var emailsPerMinute: Binding<Int> { smtpBinding(\.emailsPerMinute) }

  private var password: Binding<String> {
    Binding(
      get: { model.smtpPassword },
      set: { model.updateSMTPPassword($0) })
  }

  private var testRecipient: Binding<String> {
    Binding(
      get: { model.smtpTestRecipient },
      set: { model.updateSMTPTestRecipient($0) })
  }

  private func smtpBinding<Value>(_ keyPath: WritableKeyPath<SMTPFields, Value>) -> Binding<Value> {
    Binding(
      get: { fields[keyPath: keyPath] },
      set: { newValue in
        var updated = fields
        updated[keyPath: keyPath] = newValue
        model.updateSMTPDraft(
          host: updated.host, port: updated.port, encryption: updated.encryption,
          username: updated.username, password: model.smtpPassword, fromName: updated.fromName,
          replyTo: updated.replyTo, emailsPerMinute: updated.emailsPerMinute)
      })
  }

  private var fields: SMTPFields {
    SMTPFields(
      host: model.smtpHost, port: model.smtpPort, encryption: model.smtpEncryption,
      username: model.smtpUsername, fromName: model.smtpFromName, replyTo: model.smtpReplyTo,
      emailsPerMinute: model.smtpEmailsPerMinute)
  }

  private var confirmationPresented: Binding<Bool> {
    Binding(
      get: { confirmation != nil },
      set: { if !$0 { confirmation = nil } })
  }

  private func perform(_ action: Confirmation) {
    confirmation = nil
    switch action {
    case .save:
      Task { await model.saveSMTPSettings() }
    case .sendTest:
      Task { await model.sendSMTPTest() }
    }
  }

  private func formatted(_ date: Date?) -> String {
    date?.formatted(date: .abbreviated, time: .shortened) ?? "Not available"
  }
}

private struct SMTPFields {
  var host: String
  var port: Int
  var encryption: SMTPEncryption?
  var username: String
  var fromName: String
  var replyTo: String
  var emailsPerMinute: Int
}

private enum Confirmation {
  case save
  case sendTest

  var title: String {
    switch self {
    case .save: "Save Email Settings?"
    case .sendTest: "Send one real test email?"
    }
  }

  var buttonTitle: String {
    switch self {
    case .save: "Save Settings"
    case .sendTest: "Send Test Email"
    }
  }

  var message: String {
    switch self {
    case .save: "This shared mailbox change affects all coworkers in this Workspace."
    case .sendTest: "One real test email will be sent to the entered company recipient."
    }
  }
}
