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
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var stage = OutreachComposerStage.message
  @State private var confirmation: ComposerConfirmation?
  @State private var reportedBatchID: UUID?

  var body: some View {
    VStack(spacing: 0) {
      header
      Divider()
      content
      Divider()
      footer
    }
    .background(StudioPalette.canvas)
    .frame(minWidth: 560, idealWidth: 780, minHeight: 580, idealHeight: 760)
    .interactiveDismissDisabled(
      model.isSending || hasCustomMessage || !model.recipientEmailSelections.isEmpty
    )
    .task {
      stage = .initial(unresolvedRecipients: recipients.filter { $0.contacts.count > 1 }.count)
      await model.load(matchID: matchID, recipients: recipients)
    }
    .confirmationDialog(
      confirmationTitle,
      isPresented: confirmationPresented,
      titleVisibility: .visible
    ) {
      switch confirmation {
      case .send:
        Button("Send Now") {
          guard canSend else { return }
          Task { await model.confirmSend() }
        }
        .disabled(!canSend)
      case .discard:
        Button("Discard Draft", role: .destructive) { dismiss() }
      case .replaceTemplate(let id):
        Button("Replace Message", role: .destructive) {
          Task { await model.selectTemplate(id: id) }
        }
      case nil:
        EmptyView()
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text(confirmationMessage)
    }
    .onChange(of: model.acceptedBatch) { _, batch in
      guard let batch, reportedBatchID != batch.id else { return }
      reportedBatchID = batch.id
      onAccepted(batch)
      dismiss()
    }
  }

  private var header: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack(alignment: .center, spacing: 12) {
        Image(systemName: "paperplane")
          .font(.system(size: 22, weight: .light))
          .foregroundStyle(StudioPalette.blue)
          .frame(width: 42, height: 42)
          .background(StudioPalette.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 13))
          .accessibilityHidden(true)
        Text("Compose outreach")
          .font(.system(size: 27, weight: .semibold, design: .rounded))
          .tracking(-0.6)
          .foregroundStyle(StudioPalette.ink)
        Spacer()
        Text("\(recipients.count) \(recipients.count == 1 ? "creator" : "creators")")
          .font(.callout)
          .foregroundStyle(.secondary)
      }
      HStack(spacing: 6) {
        ForEach(Array(OutreachComposerStage.allCases.enumerated()), id: \.element) { index, item in
          Button {
            if item == .review { openReview() } else { move(to: item) }
          } label: {
            HStack(spacing: 7) {
              Text("\(index + 1)")
                .font(.caption.weight(.semibold))
                .frame(width: 22, height: 22)
                .foregroundStyle(stage == item ? StudioPalette.surface : Color.secondary)
                .background(
                  stage == item ? StudioPalette.blue : Color.secondary.opacity(0.08),
                  in: Circle())
              Text(item.rawValue)
                .font(.callout.weight(stage == item ? .semibold : .regular))
            }
            .foregroundStyle(stage == item ? Color.primary : Color.secondary)
            .padding(.vertical, 7)
            .padding(.horizontal, 9)
            .background(
              stage == item ? StudioPalette.blue.opacity(0.07) : .clear,
              in: Capsule())
          }
          .buttonStyle(.plain)
          .disabled(
            model.isLoading || model.loadError != nil || model.isSending
              || (item == .review && !canReview)
          )
          .accessibilityAddTraits(stage == item ? .isSelected : [])
          if index < 2 {
            Rectangle().fill(.separator).frame(maxWidth: 36).frame(height: 1)
          }
        }
      }
    }
    .padding(24)
    .fixedSize(horizontal: false, vertical: true)
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
          Task {
            stage = .initial(
              unresolvedRecipients: model.recipientContexts.filter { $0.contacts.count > 1 }.count)
            await model.retryLoad()
          }
        }
        .disabled(!model.canRetryLoad)
      }
    } else {
      VStack(spacing: 0) {
        if !workspaceWritesEnabled {
          Label(
            "Offline — you can edit this draft, but sending is unavailable.",
            systemImage: "wifi.slash"
          )
          .font(.caption)
          .foregroundStyle(.secondary)
          .padding(12)
          .frame(maxWidth: .infinity, alignment: .leading)
        }
        switch stage {
        case .recipients:
          ScrollView {
            VStack(alignment: .leading, spacing: 20) {
              stageHeading(
                "Choose where your message goes",
                detail:
                  "One email per creator. Review the purpose and source before choosing an address."
              )
              recipientEmailSection
            }
            .padding(24)
          }
          .disabled(model.isSending)
        case .message:
          editor
        case .review:
          reviewWorkspace
        }
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
  }

  private var editor: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        stageHeading(
          "Write a message worth opening",
          detail: "Personalized variables will be resolved for each creator in the next step.")

        HStack {
          Label(
            "\(model.creatorIDs.count) \(model.creatorIDs.count == 1 ? "recipient" : "recipients")",
            systemImage: "person.2"
          )
          .font(.callout)
          .foregroundStyle(.secondary)
          Spacer()
          Button("Review addresses") { move(to: .recipients) }
        }

        if !model.recipientIDsRequiringSelection.isEmpty {
          Label(
            "Choose an email for \(model.recipientIDsRequiringSelection.count) \(model.recipientIDsRequiringSelection.count == 1 ? "creator" : "creators") before reviewing.",
            systemImage: "envelope.badge"
          )
          .font(.caption)
          .foregroundStyle(.orange)
        }

        Picker("Template", selection: templateSelection) {
          ForEach(model.templates) { template in
            Text(template.name).tag(Optional(template.id))
          }
        }

        VStack(alignment: .leading, spacing: 6) {
          Text("Subject")
            .font(.callout.weight(.medium))
          TextField("Subject", text: subjectBinding)
            .font(.system(.title3, design: .rounded, weight: .medium))
            .textFieldStyle(OutreachDraftFieldStyle())
        }

        VStack(alignment: .leading, spacing: 6) {
          Text("Message")
            .font(.callout.weight(.medium))
          TextEditor(text: bodyBinding)
            .accessibilityLabel("Composer Message")
            .font(.system(size: 15))
            .lineSpacing(5)
            .scrollContentBackground(.hidden)
            .frame(minHeight: 260)
            .padding(16)
            .modifier(OutreachWritingSurface())
        }

        DisclosureGroup("Personalization & response buttons") {
          VStack(alignment: .leading, spacing: 8) {
            Text(
              "Use {{creator_name}}, {{game_name}}, and {{sender_name}} in your message. Markdown formatting is supported."
            )
            if let template = model.selectedTemplate {
              Text(
                "Response buttons: “\(template.acceptedLabel)” and “\(template.declinedLabel)”. These are managed by the selected template and tracked by the system."
              )
            }
          }
          .font(.caption)
          .foregroundStyle(.secondary)
          .padding(.top, 6)
        }
      }
      .frame(maxWidth: 760, alignment: .leading)
      .padding(24)
      .frame(maxWidth: .infinity)
    }
    .disabled(model.isLoading || model.isSending || model.acceptedBatch != nil)
  }

  @ViewBuilder private var recipientEmailSection: some View {
    if !model.recipientContexts.isEmpty {
      VStack(alignment: .leading, spacing: 0) {
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
                .font(.system(.title3, design: .rounded, weight: .semibold))

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
            .padding(16)
            .frame(maxWidth: .infinity, alignment: .leading)
            .modifier(OutreachWritingSurface())

          }
        }
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
    var parts = [contact.email]
    if let purpose = contact.purpose,
      !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    {
      parts.append(purpose)
    }
    parts.append(contact.source)
    parts.append(contact.validationState)
    return parts.joined(separator: " — ")
  }

  private var reviewWorkspace: some View {
    VStack(alignment: .leading, spacing: 0) {
      stageHeading(
        "Review the email each creator will receive",
        detail:
          "These previews are rendered by the server. Sending queues one email per selected creator."
      )
      .padding(24)

      if let error = model.previewError {
        HStack(alignment: .top) {
          errorBanner(error)
          Button("Try Again") { Task { await model.refreshPreview() } }
            .disabled(!model.canRefreshPreview)
        }
        .padding(.horizontal, 24)
      }
      if let error = model.sendError {
        errorBanner(error)
          .padding(.horizontal, 24)
      }
      previewPane
    }
  }

  private var previewPane: some View {
    VStack(spacing: 0) {
      if !model.previews.isEmpty {
        HStack {
          Picker(
            "Preview for",
            selection: Binding(
              get: { model.selectedRecipientID },
              set: { if let id = $0 { model.selectRecipient(id: id) } })
          ) {
            ForEach(model.previews) { preview in
              Text("\(preview.creatorName) — \(preview.recipientEmail)")
                .tag(Optional(preview.creatorID))
            }
          }
          .pickerStyle(.menu)
          .disabled(model.isSending)
          Spacer(minLength: 0)
          Text("\(model.previews.count) \(model.previews.count == 1 ? "preview" : "previews")")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 12)
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
        ContentUnavailableView {
          Label("Preview required", systemImage: "envelope.open")
        } description: {
          Text("Your draft is kept. Render an up-to-date preview before sending.")
        } actions: {
          if model.previewError == nil {
            Button("Render Preview") { Task { await model.refreshPreview() } }
              .disabled(!model.canRefreshPreview)
          }
        }
      }
    }
  }

  private var footer: some View {
    HStack {
      if model.isSending {
        ProgressView()
          .controlSize(.small)
        Text("Submitting…")
          .font(.caption)
          .foregroundStyle(.secondary)
          .accessibilityLabel("Submitting batch for queued delivery")
      }
      Button("Cancel", role: .cancel) {
        if hasCustomMessage || !model.recipientEmailSelections.isEmpty {
          confirmation = .discard
        } else {
          dismiss()
        }
      }
      .disabled(model.isSending)
      Spacer()
      if model.loadError == nil && !model.isLoading {
        if let previous = stage.previous {
          Button("Back") { move(to: previous) }
            .disabled(model.isSending)
        }
        switch stage {
        case .recipients:
          Button("Continue to message") { move(to: .message) }
            .buttonStyle(.borderedProminent)
            .disabled(!model.recipientIDsRequiringSelection.isEmpty || model.isSending)
        case .message:
          Button("Review emails") { openReview() }
            .buttonStyle(.borderedProminent)
            .disabled(!canReview)
        case .review:
          Button(model.sendError == nil ? "Send Outreach" : "Retry Send") {
            guard canSend else { return }
            confirmation = .send
          }
          .buttonStyle(.borderedProminent)
          .disabled(!canSend)
        }
      }
    }
    .padding(20)
    .fixedSize(horizontal: false, vertical: true)
    .background(StudioPalette.surface.opacity(0.75))
  }

  private var templateSelection: Binding<UUID?> {
    Binding(
      get: { model.selectedTemplate?.id },
      set: { id in
        guard let id, id != model.selectedTemplate?.id else { return }
        if hasCustomMessage {
          confirmation = .replaceTemplate(id)
        } else {
          Task { await model.selectTemplate(id: id) }
        }
      })
  }

  private var canReview: Bool {
    !model.isSending && model.selectedTemplate != nil
      && OutreachComposerStage.canReview(
        unresolvedRecipients: model.recipientIDsRequiringSelection.count,
        subject: model.subjectDraft, body: model.bodyMarkdownDraft)
  }

  private var hasCustomMessage: Bool {
    guard let template = model.selectedTemplate else { return false }
    return model.subjectDraft != template.subjectTemplate
      || model.bodyMarkdownDraft != template.bodyMarkdown
  }

  private func openReview() {
    guard canReview else { return }
    move(to: .review)
    if !model.canConfirmSend && !model.isPreviewing && model.previewError == nil {
      Task { await model.refreshPreview() }
    }
  }

  private func move(to next: OutreachComposerStage) {
    withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
      stage = next
    }
  }

  private func stageHeading(_ title: String, detail: String) -> some View {
    VStack(alignment: .leading, spacing: 7) {
      Text(title)
        .font(.system(.title3, design: .rounded, weight: .semibold))
        .foregroundStyle(StudioPalette.ink)
      Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(
        horizontal: false, vertical: true)
    }
  }

  private var confirmationPresented: Binding<Bool> {
    Binding(get: { confirmation != nil }, set: { if !$0 { confirmation = nil } })
  }

  private var confirmationTitle: String {
    switch confirmation {
    case .send:
      "Send outreach to \(model.creatorIDs.count) \(model.creatorIDs.count == 1 ? "creator" : "creators")?"
    case .discard: "Discard this outreach draft?"
    case .replaceTemplate: "Replace your message with this template?"
    case nil: "Confirm outreach"
    }
  }

  private var confirmationMessage: String {
    switch confirmation {
    case .send:
      "The server will accept this batch and queue delivery. A queued email cannot be recalled here."
    case .discard:
      "Your unsent message and email selections will be discarded. No email will be sent."
    case .replaceTemplate:
      "This replaces your subject and message. Your recipient choices are kept; the server preview will be refreshed."
    case nil: ""
    }
  }

  private enum ComposerConfirmation {
    case send
    case discard
    case replaceTemplate(UUID)
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
