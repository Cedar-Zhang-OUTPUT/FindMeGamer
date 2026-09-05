import FindMeGamerCore
import SwiftUI

enum OutreachComposerAccessibility {
  static func recipientEmail(_ creatorID: UUID) -> String {
    "outreach.recipient-email.\(creatorID.uuidString)"
  }
}

struct OutreachComposerSheet: View {
  @Bindable var model: OutreachComposerModel
  let matchID: UUID
  let recipients: [OutreachRecipientContext]
  let onAccepted: (SendBatch) -> Void

  @Environment(\.dismiss) private var dismiss
  @Environment(\.workspaceWritesEnabled) private var workspaceWritesEnabled
  @State private var isShowingConfirmation = false
  @State private var reportedBatchID: UUID?

  var body: some View {
    VStack(spacing: 0) {
      header
      Divider()
      content
      Divider()
      footer
    }
    .frame(minWidth: 760, idealWidth: 860, minHeight: 620, idealHeight: 700)
    .interactiveDismissDisabled(model.isSending)
    .task {
      await model.load(matchID: matchID, recipients: recipients)
    }
    .confirmationDialog(
      "Send outreach to \(model.creatorIDs.count) creators?",
      isPresented: $isShowingConfirmation,
      titleVisibility: .visible
    ) {
      Button("Send Now") {
        guard canSend else { return }
        Task { await model.confirmSend() }
      }
      .disabled(!canSend)
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("The server will accept this batch and queue delivery.")
    }
    .onChange(of: model.acceptedBatch) { _, batch in
      guard let batch, reportedBatchID != batch.id else { return }
      reportedBatchID = batch.id
      onAccepted(batch)
      dismiss()
    }
  }

  private var header: some View {
    HStack(alignment: .firstTextBaseline) {
      VStack(alignment: .leading, spacing: 4) {
        Text("Compose Outreach")
          .font(.title2.bold())
        Text("\(model.creatorIDs.count) recipients")
          .foregroundStyle(.secondary)
      }
      Spacer()
      if model.isLoading {
        ProgressView()
          .controlSize(.small)
      }
    }
    .padding(20)
  }

  @ViewBuilder private var content: some View {
    if model.isLoading {
      VStack(spacing: 10) {
        ProgressView()
        Text("Loading Outreach Templates…")
          .foregroundStyle(.secondary)
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    } else if let loadError = model.loadError {
      ContentUnavailableView {
        Label("Could not compose Outreach", systemImage: "exclamationmark.triangle")
      } description: {
        Text(loadError)
      } actions: {
        Button("Try Again") {
          Task { await model.retryLoad() }
        }
        .disabled(!model.canRetryLoad)
      }
    } else {
      HSplitView {
        editor
          .frame(minWidth: 310, idealWidth: 360)
        previewPane
          .frame(minWidth: 390, idealWidth: 500)
      }
    }
  }

  private var editor: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        recipientEmailSection

        Picker("Template", selection: templateSelection) {
          ForEach(model.templates) { template in
            Text(template.name).tag(Optional(template.id))
          }
        }

        VStack(alignment: .leading, spacing: 6) {
          Text("Subject")
            .font(.headline)
          TextField("Subject", text: subjectBinding)
            .textFieldStyle(.roundedBorder)
        }

        VStack(alignment: .leading, spacing: 6) {
          Text("Markdown message")
            .font(.headline)
          TextEditor(text: bodyBinding)
            .font(.body)
            .frame(minHeight: 240)
            .padding(5)
            .background(.background, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(.separator))
        }

        HStack {
          if model.isPreviewing {
            ProgressView()
              .controlSize(.small)
            Text("Rendering per-Creator previews…")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
          Spacer()
          Button("Refresh Preview") {
            Task { await model.refreshPreview() }
          }
          .disabled(!model.canRefreshPreview)
        }

        if let previewError = model.previewError {
          errorBanner(previewError)
        }
        if let sendError = model.sendError {
          errorBanner(sendError)
        }
      }
      .padding(18)
    }
    .disabled(model.isLoading || model.isSending || model.acceptedBatch != nil)
  }

  @ViewBuilder private var recipientEmailSection: some View {
    if !model.recipientContexts.isEmpty {
      GroupBox("Recipient Emails") {
        VStack(alignment: .leading, spacing: 12) {
          if !model.recipientIDsRequiringSelection.isEmpty {
            Label(
              "Choose exactly one email for each Creator with multiple addresses.",
              systemImage: "envelope.badge"
            )
            .font(.caption)
            .foregroundStyle(.orange)
          }

          ForEach(model.recipientContexts) { recipient in
            VStack(alignment: .leading, spacing: 6) {
              Text(recipient.creatorName)
                .font(.callout.weight(.semibold))

              if recipient.contacts.count == 1, let contact = recipient.contacts.first {
                Label(contact.email, systemImage: "checkmark.circle.fill")
                  .font(.callout)
                  .foregroundStyle(.secondary)
                  .textSelection(.enabled)
                contactMetadata(contact)
              } else {
                Menu {
                  ForEach(Array(recipient.contacts.enumerated()), id: \.offset) { _, contact in
                    Button {
                      Task {
                        await model.selectRecipientEmail(
                          contact.email, creatorID: recipient.creatorID)
                      }
                    } label: {
                      Text(contactMenuTitle(contact))
                    }
                  }
                } label: {
                  HStack {
                    Text(model.selectedEmail(for: recipient.creatorID) ?? "Choose one email…")
                    Spacer()
                    Image(systemName: "chevron.up.chevron.down")
                      .font(.caption2)
                  }
                  .contentShape(Rectangle())
                }
                .menuStyle(.borderlessButton)
                .accessibilityLabel("Email for \(recipient.creatorName)")
                .accessibilityIdentifier(
                  OutreachComposerAccessibility.recipientEmail(recipient.creatorID))

                if let selectedEmail = model.selectedEmail(for: recipient.creatorID),
                  let selectedContact = recipient.contacts.first(where: {
                    $0.email == selectedEmail
                  })
                {
                  contactMetadata(selectedContact)
                }
              }
            }

            if recipient.id != model.recipientContexts.last?.id {
              Divider()
            }
          }
        }
        .padding(.top, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
      }
    }
  }

  @ViewBuilder
  private func contactMetadata(_ contact: OutreachRecipientContact) -> some View {
    HStack(spacing: 6) {
      if let purpose = contact.purpose,
        !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      {
        Text(purpose)
      }
      Text(contact.source)
      Text(contact.validationState)
    }
    .font(.caption2)
    .foregroundStyle(.secondary)
  }

  private func contactMenuTitle(_ contact: OutreachRecipientContact) -> String {
    guard let purpose = contact.purpose,
      !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else {
      return contact.email
    }
    return "\(contact.email) — \(purpose)"
  }

  private var previewPane: some View {
    VStack(spacing: 0) {
      if !model.previews.isEmpty {
        ScrollView(.horizontal) {
          HStack(spacing: 8) {
            ForEach(model.previews) { preview in
              Button(preview.creatorName) {
                model.selectRecipient(id: preview.creatorID)
              }
              .buttonStyle(.bordered)
              .tint(model.selectedRecipientID == preview.creatorID ? .accentColor : .secondary)
            }
          }
          .padding(.horizontal, 16)
          .padding(.vertical, 10)
        }
        Divider()
      }

      if let preview = model.selectedPreview, let template = model.selectedTemplate {
        RenderedEmailPreview(
          preview: preview, acceptedLabel: template.acceptedLabel,
          declinedLabel: template.declinedLabel)
      } else if model.isPreviewing {
        ProgressView("Rendering preview…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else {
        ContentUnavailableView(
          "Preview required", systemImage: "envelope.open",
          description: Text("Refresh the server-rendered preview before sending."))
      }
    }
  }

  private var footer: some View {
    HStack {
      if model.isSending {
        ProgressView()
          .controlSize(.small)
        Text("Submitting batch for queued delivery…")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      Spacer()
      Button("Cancel", role: .cancel) {
        dismiss()
      }
      .disabled(model.isSending)
      Button("Send Outreach") {
        guard canSend else { return }
        isShowingConfirmation = true
      }
      .buttonStyle(.borderedProminent)
      .disabled(!canSend)
    }
    .padding(16)
  }

  private var templateSelection: Binding<UUID?> {
    Binding(
      get: { model.selectedTemplate?.id },
      set: { id in
        guard let id else { return }
        Task { await model.selectTemplate(id: id) }
      })
  }

  private var canSend: Bool {
    OutreachComposerActionPolicy.canSend(
      workspaceWritesEnabled: workspaceWritesEnabled,
      modelCanConfirmSend: model.canConfirmSend)
  }

  private var subjectBinding: Binding<String> {
    Binding(
      get: { model.subjectDraft },
      set: { model.updateOverride(subject: $0, bodyMarkdown: model.bodyMarkdownDraft) })
  }

  private var bodyBinding: Binding<String> {
    Binding(
      get: { model.bodyMarkdownDraft },
      set: { model.updateOverride(subject: model.subjectDraft, bodyMarkdown: $0) })
  }

  private func errorBanner(_ message: String) -> some View {
    Label(message, systemImage: "exclamationmark.triangle")
      .font(.callout)
      .foregroundStyle(.red)
      .textSelection(.enabled)
      .padding(10)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
  }
}
