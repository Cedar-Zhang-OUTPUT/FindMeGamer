import SwiftUI

struct CreatorProfileDetail: View {
  let presentation: CreatorProfilePresentation
  @Binding var manualDraft: CreatorManualDraft
  let writesEnabled: Bool
  let isSaving: Bool
  let onSave: () -> Void
  var destination: ProfileDetailDestination = .overview
  var hasUnsavedChanges = true

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      switch destination {
      case .overview:
        if presentation.staleWarning == nil {
          ProfileOverview(fields: presentation.briefFields, type: .creator)
        } else {
          ContentUnavailableView(
            "Refresh this creator profile",
            systemImage: "arrow.clockwise",
            description: Text(
              "Use Re-analyze above to request fresh YouTube data. Your manual contacts and notes are still available."
            ))
        }
      case .evidence:
        WorkspaceSectionHeader(
          "Sources & Analysis",
          subtitle: "Source facts, AI analysis, and audience inference are labeled separately.")
        ProfileEvidenceSection(
          title: "YouTube source facts", subtitle: "Public channel data · not inferred",
          symbol: "play.rectangle", tone: .identity
        ) {
          sourceColumn
        }
        analysisColumn
      case .contacts:
        WorkspaceSectionHeader(
          "Contacts & Notes",
          subtitle:
            "Review each address and its purpose. Add your own contact without replacing discovered sources."
        )
        contactSection
        manualEditor
      }
    }
  }

  private var sourceColumn: some View {
    FactSection(title: "Source Facts", fields: presentation.sourceFacts)
      .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private var analysisColumn: some View {
    VStack(alignment: .leading, spacing: 14) {
      ForEach(
        CreatorProfileSection.allCases.filter {
          ![.audienceInference, .promotionFit, .contact, .creatorBrief].contains($0)
        }, id: \.self
      ) { section in
        evidenceSection(section, title: "AI Analysis — \(section.title)")
      }
      evidenceSection(.audienceInference, title: "AI Inference — Audience")
      evidenceSection(.promotionFit, title: "AI Analysis — Promotion Fit")
    }
    .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private func evidenceSection(_ section: CreatorProfileSection, title: String) -> some View {
    ProfileEvidenceSection(
      title: section.title,
      subtitle: section == .audienceInference
        ? "AI inference · not verified demographics"
        : "AI interpretation of the available evidence",
      symbol: evidenceSymbol(section), tone: evidenceTone(section)
    ) {
      FactSection(title: title, fields: presentation.sections[section] ?? [])
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
    VStack(alignment: .leading, spacing: 12) {
      if presentation.contacts.isEmpty {
        Label("No contact address yet. Add the one you use below.", systemImage: "envelope.open")
          .font(.callout)
          .foregroundStyle(.secondary)
          .padding(18)
          .frame(maxWidth: .infinity, alignment: .leading)
          .background(StudioPalette.blue.opacity(0.045), in: RoundedRectangle(cornerRadius: 18))
      } else {
        ForEach(Array(presentation.contacts.enumerated()), id: \.offset) { _, contact in
          ProfileContactCard(contact: contact)
        }
      }
    }
  }

  private var manualEditor: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack(spacing: 10) {
        Image(systemName: "square.and.pencil")
          .font(.system(size: 16, weight: .medium))
          .foregroundStyle(StudioPalette.coral)
          .frame(width: 36, height: 36)
          .background(StudioPalette.coral.opacity(0.1), in: RoundedRectangle(cornerRadius: 12))
        VStack(alignment: .leading, spacing: 2) {
          Text("Your contact & notes").font(.headline)
          Text("Context only you can add.").font(.caption).foregroundStyle(.secondary)
        }
      }
      VStack(alignment: .leading, spacing: 10) {
        Text("Manual Email")
          .font(.subheadline.weight(.medium))
        TextField("name@example.com", text: $manualDraft.email)
          .textContentType(.emailAddress)
          .accessibilityIdentifier("profile.manual.email")
          .accessibilityLabel("Manual Email")
        Text("Leave the email empty to remove your manual override. Discovered contacts are kept.")
          .font(.caption)
          .foregroundStyle(.secondary)

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
            Spacer()
            if isSaving {
              ProgressView().controlSize(.small)
            }
            Button("Save Contact & Notes", action: onSave)
              .buttonStyle(.borderedProminent)
              .disabled(
                !hasUnsavedChanges
                  || !ProfileActionPolicy.canSaveManual(
                    writesEnabled: writesEnabled,
                    isInFlight: isSaving,
                    isValid: manualDraft.validationMessage == nil)
              )
              .accessibilityIdentifier("profile.manual.save")
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

  var body: some View {
    HStack(alignment: .top, spacing: 14) {
      Image(systemName: contact.availability == .manual ? "pencil" : "envelope")
        .font(.system(size: 17, weight: .medium))
        .foregroundStyle(StudioPalette.blue)
        .frame(width: 42, height: 42)
        .background(StudioPalette.blue.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
        .accessibilityHidden(true)

      VStack(alignment: .leading, spacing: 9) {
        if let purpose = contact.purpose,
          !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        {
          Text(purpose)
            .font(.caption.weight(.semibold))
            .foregroundStyle(StudioPalette.blue)
            .accessibilityLabel("Purpose: \(purpose)")
        }
        Text(contact.email)
          .font(.system(.headline, design: .rounded))
          .textSelection(.enabled)
          .fixedSize(horizontal: false, vertical: true)

        ViewThatFits(in: .horizontal) {
          HStack(spacing: 8) {
            availability
            validation
          }
          VStack(alignment: .leading, spacing: 7) {
            availability
            validation
          }
        }

        HStack(alignment: .firstTextBaseline, spacing: 4) {
          Text("Source").foregroundStyle(.secondary)
          if let sourceURL = contact.sourceURL {
            Link(contact.source, destination: sourceURL)
          } else {
            Text(contact.source).foregroundStyle(.secondary)
          }
        }
        .font(.caption)
      }
      .frame(maxWidth: .infinity, alignment: .leading)
    }
    .padding(18)
    .background(StudioPalette.blue.opacity(0.04), in: RoundedRectangle(cornerRadius: 19))
    .accessibilityElement(children: .contain)
  }

  private var availability: some View {
    Text(contact.availability.displayName)
      .font(.caption)
      .foregroundStyle(.secondary)
      .padding(.horizontal, 8)
      .padding(.vertical, 4)
      .background(StudioPalette.blue.opacity(0.075), in: Capsule())
      .accessibilityLabel("Availability: \(contact.availability.displayName)")
  }

  private var validation: some View {
    Text("Validation: \(contact.validationState)")
      .font(.caption)
      .foregroundStyle(.secondary)
  }
}
