import SwiftUI

struct CreatorProfileDetail: View {
  let presentation: CreatorProfilePresentation
  @Binding var manualDraft: CreatorManualDraft
  let writesEnabled: Bool
  let isSaving: Bool
  let onSave: () -> Void
  var destination: ProfileDetailDestination = .overview
  var hasUnsavedChanges = true
  var manualEditorMode: ProfileManualEditorMode = .summary
  var onEditManual: () -> Void = {}
  var onDiscardManual: () -> Void = {}
  var onReanalyze: () -> Void = {}
  var isReanalyzing = false
  var onOpenContacts: () -> Void = {}

  @State private var isConfirmingDiscard = false
  @State private var notesExpanded = false

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      switch destination {
      case .overview:
        if presentation.staleWarning == nil || !presentation.briefFields.isEmpty {
          ProfileOverview(fields: presentation.briefFields, type: .creator)
          if let warning = presentation.staleWarning {
            Label(warning + " Manual values are shown.", systemImage: "exclamationmark.triangle")
              .font(.callout).foregroundStyle(.secondary)
          }
        } else {
          ContentUnavailableView {
            Label("YouTube data is stale", systemImage: "arrow.clockwise")
          } actions: {
            Button(isReanalyzing ? "Requesting…" : "Re-analyze", action: onReanalyze)
              .buttonStyle(.borderedProminent)
              .disabled(!writesEnabled || isReanalyzing)
            Button("Contacts & Notes", action: onOpenContacts)
          }
        }
      case .evidence:
        ProfileEvidenceSection(
          title: "YouTube",
          symbol: "play.rectangle", tone: .identity
        ) {
          sourceColumn
        }
        analysisColumn
      case .contacts:
        contactSection
        if manualEditorMode == .editing || hasUnsavedChanges {
          manualEditor
        } else {
          manualSummary
        }
      }
    }
    .confirmationDialog(
      "Discard contact and note edits?", isPresented: $isConfirmingDiscard,
      titleVisibility: .visible
    ) {
      Button("Discard Changes", role: .destructive, action: onDiscardManual)
      Button("Keep Editing", role: .cancel) {}
    } message: {
      Text("Your saved contact and notes are unchanged.")
    }
  }

  private var sourceColumn: some View {
    FactSection(fields: presentation.sourceFacts)
      .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private var analysisColumn: some View {
    VStack(alignment: .leading, spacing: 14) {
      Label("AI Analysis", systemImage: "sparkles")
        .font(.caption.weight(.medium))
        .foregroundStyle(.secondary)
        .accessibilityAddTraits(.isHeader)
      ForEach(
        CreatorProfileSection.allCases.filter {
          ![.audienceInference, .promotionFit, .contact, .creatorBrief].contains($0)
        }, id: \.self
      ) { section in
        evidenceSection(section)
      }
      evidenceSection(.audienceInference)
      evidenceSection(.promotionFit)
    }
    .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private func evidenceSection(_ section: CreatorProfileSection) -> some View {
    ProfileEvidenceSection(
      title: section.title,
      subtitle: section == .audienceInference
        ? "Unverified demographics"
        : nil,
      symbol: evidenceSymbol(section), tone: evidenceTone(section)
    ) {
      FactSection(contextTitle: section.title, fields: presentation.sections[section] ?? [])
    }
  }

  private func evidenceSymbol(_ section: CreatorProfileSection) -> String {
    switch section {
    case .overview, .creatorBrief: "text.quote"
    case .performance: "chart.bar.xaxis"
    case .content: "play.rectangle.on.rectangle"
    case .audienceInference: "person.2"
    case .promotionFit: "sparkles"
    case .contact: "envelope"
    }
  }

  private func evidenceTone(_ section: CreatorProfileSection) -> ProfileStoryTone {
    switch section {
    case .audienceInference, .performance: .audience
    case .promotionFit: .opportunity
    default: .identity
    }
  }

  private var contactSection: some View {
    VStack(alignment: .leading, spacing: 0) {
      if presentation.contacts.isEmpty {
        Label("No contacts", systemImage: "envelope.open")
          .font(.callout)
          .foregroundStyle(.secondary)
          .padding(.vertical, 12)
          .frame(maxWidth: .infinity, alignment: .leading)
      } else {
        ForEach(Array(presentation.contacts.enumerated()), id: \.offset) { index, contact in
          if index > 0 { Divider() }
          ProfileContactCard(contact: contact)
        }
      }
    }
  }

  private var manualSummary: some View {
    VStack(alignment: .leading, spacing: 14) {
      if !manualDraft.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        DisclosureGroup(isExpanded: $notesExpanded) {
          Text(manualDraft.notes)
            .font(.callout)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.top, 8)
        } label: {
          VStack(alignment: .leading, spacing: 5) {
            Text("Notes").font(.subheadline.weight(.semibold))
            if !notesExpanded {
              Text(manualDraft.notes)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            }
          }
        }
      }
      Button(action: onEditManual) {
        Label(
          presentation.contacts.isEmpty ? "Add Contact & Notes" : "Edit Contact & Notes",
          systemImage: "square.and.pencil")
      }
      .buttonStyle(.bordered)
      .accessibilityIdentifier("profile.manual.edit")
    }
    .padding(.top, 8)
  }

  private var manualEditor: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text("Contact & Notes").font(.headline)
      VStack(alignment: .leading, spacing: 10) {
        HStack {
          Text("Manual Email").font(.subheadline.weight(.medium))
          Spacer()
          if presentation.contacts.contains(where: { $0.availability == .manual }),
            manualDraft.normalizedEmail != nil
          {
            Button("Remove Manual Email", role: .destructive) { manualDraft.email = "" }
              .buttonStyle(.borderless)
              .font(.caption)
              .disabled(isSaving)
          }
        }
        TextField("name@example.com", text: $manualDraft.email)
          .textContentType(.emailAddress)
          .accessibilityIdentifier("profile.manual.email")
          .accessibilityLabel("Manual Email")
        if presentation.contacts.contains(where: { $0.availability == .manual }),
          manualDraft.normalizedEmail == nil
        {
          Label(
            "Saving removes your manual email. Discovered contacts stay.",
            systemImage: "minus.circle"
          )
          .font(.caption)
          .foregroundStyle(.secondary)
        }

        Text("Notes")
          .font(.caption)
          .foregroundStyle(.secondary)
        TextEditor(text: $manualDraft.notes)
          .accessibilityLabel("Profile Notes")
          .frame(minHeight: 100)
          .accessibilityIdentifier("profile.manual.notes")
          .scrollContentBackground(.hidden)
          .padding(8)
          .background(StudioPalette.surface, in: RoundedRectangle(cornerRadius: 12))

        VStack(alignment: .leading, spacing: 10) {
          if let validationMessage = manualDraft.validationMessage {
            Label(validationMessage, systemImage: "exclamationmark.triangle")
              .foregroundStyle(.red)
              .font(.caption)
          }
          HStack {
            Button("Cancel") {
              if hasUnsavedChanges { isConfirmingDiscard = true } else { onDiscardManual() }
            }
            .disabled(isSaving)
            .accessibilityIdentifier("profile.manual.cancel")
            Spacer()
            if isSaving {
              ProgressView().controlSize(.small)
            }
            Button("Save", action: onSave)
              .buttonStyle(.borderedProminent)
              .disabled(
                !hasUnsavedChanges
                  || !ProfileActionPolicy.canSaveManual(
                    writesEnabled: writesEnabled,
                    isInFlight: isSaving,
                    isValid: manualDraft.validationMessage == nil)
              )
              .accessibilityIdentifier("profile.manual.save")
              .accessibilityLabel("Save contact and notes")
              .help("Save the manual contact and notes")
          }
        }
      }
    }
    .padding(18)
    .background(StudioPalette.coral.opacity(0.035), in: RoundedRectangle(cornerRadius: 19))
  }
}

private struct ProfileContactCard: View {
  let contact: CreatorContactPresentation
  @State private var isShowingSource = false

  var body: some View {
    HStack(alignment: .top, spacing: 12) {
      VStack(alignment: .leading, spacing: 6) {
        if let purpose = contact.purpose,
          !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        {
          Text(purpose)
            .font(.caption.weight(.semibold))
            .foregroundStyle(StudioPalette.blue)
            .accessibilityLabel("Purpose: \(purpose)")
        }
        Text(contact.email)
          .font(.system(.body, design: .rounded, weight: .semibold))
          .textSelection(.enabled)
          .fixedSize(horizontal: false, vertical: true)

        ViewThatFits(in: .horizontal) {
          HStack(spacing: 10) {
            availability
            validation
            source
          }
          VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 10) {
              availability
              validation
            }
            source
          }
        }
        .font(.caption)
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
    .padding(.vertical, 12)
    .accessibilityElement(children: .contain)
  }

  private var availability: some View {
    Text(contact.availability.displayName)
      .font(.caption)
      .foregroundStyle(.secondary)
      .accessibilityLabel("Availability: \(contact.availability.displayName)")
  }

  private var validation: some View {
    Text("Validation: \(contact.validationState)")
      .font(.caption)
      .foregroundStyle(.secondary)
  }

  private var source: some View {
    DisclosureGroup(isExpanded: $isShowingSource) {
      VStack(alignment: .leading, spacing: 10) {
        Text(contact.source)
          .font(.subheadline)
          .textSelection(.enabled)
          .fixedSize(horizontal: false, vertical: true)
        if let sourceURL = contact.sourceURL {
          Link(destination: sourceURL) {
            Label(sourceURL.host ?? "Open Source", systemImage: "arrow.up.right")
              .fixedSize(horizontal: false, vertical: true)
          }
          .accessibilityLabel("Open contact source")
          Text(sourceURL.absoluteString)
            .font(.caption)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
            .fixedSize(horizontal: false, vertical: true)
        }
      }
      .padding(.top, 8)
      .frame(maxWidth: .infinity, alignment: .leading)
    } label: {
      Text("Source").accessibilityLabel("Source for \(contact.email)")
    }
  }
}
