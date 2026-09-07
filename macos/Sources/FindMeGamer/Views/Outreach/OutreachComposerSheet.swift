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
  @State private var messageEditing = OutreachTextEditing()

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
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .center, spacing: 12) {
        Image(systemName: "paperplane")
          .font(.system(size: 22, weight: .light))
          .foregroundStyle(StudioPalette.blue)
          .frame(width: 42, height: 42)
          .background(StudioPalette.blue.opacity(0.09), in: RoundedRectangle(cornerRadius: 13))
          .accessibilityHidden(true)
        Text("New outreach")
          .font(.system(size: 22, weight: .semibold, design: .rounded))
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
              if item == .recipients, !model.recipientIDsRequiringSelection.isEmpty {
                Label(
                  "\(model.recipientIDsRequiringSelection.count)",
                  systemImage: "exclamationmark.circle"
                )
                .font(.caption.weight(.medium))
                .foregroundStyle(StudioPalette.amber)
                .accessibilityLabel(
                  "\(model.recipientIDsRequiringSelection.count) recipients need an address")
              }
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
    .padding(20)
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
            "Offline · Sending unavailable",
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
          HStack {
            Text("Message").font(.callout.weight(.medium))
            Spacer()
            OutreachVariableMenu(editing: messageEditing)
          }
          OutreachMessageEditor(
            text: bodyBinding, editing: messageEditing, accessibilityLabel: "Composer Message"
          )
          .frame(minHeight: 260)
          .padding(16)
          .modifier(OutreachWritingSurface())
        }

        if let template = model.selectedTemplate {
          OutreachResponseButtons(
            accepted: template.acceptedLabel, declined: template.declinedLabel)
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
          ForEach(model.recipientContexts) { recipient in
            VStack(alignment: .leading, spacing: 6) {
              HStack {
                Text(recipient.creatorName)
                  .font(.system(.title3, design: .rounded, weight: .semibold))
                Spacer()
                if model.recipientIDsRequiringSelection.contains(recipient.creatorID) {
                  Text("Choose an address")
                    .font(.callout)
                    .foregroundStyle(StudioPalette.amber)
                }
              }

              if recipient.contacts.count == 1, let contact = recipient.contacts.first {
                Label(contact.email, systemImage: "checkmark.circle.fill")
                  .font(.callout)
                  .foregroundStyle(.secondary)
                  .textSelection(.enabled)
                contactMetadata(contact)
              } else {
                ForEach(Array(recipient.contacts.enumerated()), id: \.offset) { _, contact in
                  recipientChoice(contact, recipient: recipient)
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
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 8) { contactFacts(contact) }
      VStack(alignment: .leading, spacing: 4) { contactFacts(contact) }
    }
    .font(.callout)
    .foregroundStyle(.secondary)
  }

  @ViewBuilder private func contactFacts(_ contact: OutreachRecipientContact) -> some View {
    if let purpose = contact.purpose,
      !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    {
      Text(purpose).foregroundStyle(StudioPalette.ink)
    }
    Text(contact.source.replacingOccurrences(of: "_", with: " ").capitalized)
    Label(
      contact.validationState.replacingOccurrences(of: "_", with: " ").capitalized,
      systemImage: contact.validationState.lowercased() == "valid"
        ? "checkmark.seal" : "info.circle"
    )
    .foregroundStyle(
      contact.validationState.lowercased() == "valid"
        || contact.validationState.lowercased() == "demo"
        ? Color.secondary : StudioPalette.amber)
  }

  private func recipientChoice(
    _ contact: OutreachRecipientContact, recipient: OutreachRecipientContext
  ) -> some View {
    let selected =
      model.selectedEmail(for: recipient.creatorID)?.caseInsensitiveCompare(contact.email)
      == .orderedSame
    return Button {
      Task { await model.selectRecipientEmail(contact.email, creatorID: recipient.creatorID) }
    } label: {
      HStack(alignment: .top, spacing: 10) {
        Image(systemName: selected ? "largecircle.fill.circle" : "circle")
          .foregroundStyle(selected ? StudioPalette.blue : Color.secondary)
          .font(.system(size: 18))
        VStack(alignment: .leading, spacing: 5) {
          Text(contact.email).font(.body).foregroundStyle(StudioPalette.ink)
          contactMetadata(contact)
        }
        Spacer(minLength: 0)
      }
      .padding(12)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(
        selected ? StudioPalette.blue.opacity(0.07) : .clear, in: RoundedRectangle(cornerRadius: 10)
      )
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityAddTraits(selected ? .isSelected : [])
    .accessibilityIdentifier(
      "\(OutreachComposerAccessibility.recipientEmail(recipient.creatorID)).\(contact.email)")
  }

  private var reviewWorkspace: some View {
    VStack(alignment: .leading, spacing: 0) {
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
      if model.previews.count > 1 {
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
          Button {
            if let id = previewNavigation.previousID { model.selectRecipient(id: id) }
          } label: {
            Label("Previous email", systemImage: "chevron.left").labelStyle(.iconOnly)
          }
          .disabled(model.isSending || previewNavigation.previousID == nil)
          .help("Previous email")
          Text(previewNavigation.position)
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
            .fixedSize()
          Button {
            if let id = previewNavigation.nextID { model.selectRecipient(id: id) }
          } label: {
            Label("Next email", systemImage: "chevron.right").labelStyle(.iconOnly)
          }
          .disabled(model.isSending || previewNavigation.nextID == nil)
          .help("Next email")
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
          Text("Preview must match the current draft.")
        } actions: {
          if model.previewError == nil {
            Button("Render Preview") { Task { await model.refreshPreview() } }
              .disabled(!model.canRefreshPreview)
          }
        }
      }
    }
  }

  private var previewNavigation: OutreachPreviewNavigation {
    OutreachPreviewNavigation(
      ids: model.previews.map(\.creatorID), selectedID: model.selectedRecipientID)
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
          Button("Write message") { move(to: .message) }
            .buttonStyle(.borderedProminent)
            .disabled(!model.recipientIDsRequiringSelection.isEmpty || model.isSending)
        case .message:
          Button("Review emails") { openReview() }
            .buttonStyle(.borderedProminent)
            .disabled(!canReview)
        case .review:
          Button(
            model.sendError == nil
              ? "Send \(model.creatorIDs.count) \(model.creatorIDs.count == 1 ? "email" : "emails")"
              : "Retry send"
          ) {
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
      "Queues one email per creator. Queued emails cannot be recalled here."
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
