import SwiftUI

struct CreatorProfileDetail: View {
  let presentation: CreatorProfilePresentation
  @Binding var manualDraft: CreatorManualDraft
  let writesEnabled: Bool
  let isSaving: Bool
  let onSave: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      if let warning = presentation.staleWarning {
        Label(warning, systemImage: "exclamationmark.triangle.fill")
          .foregroundStyle(.orange)
          .font(.headline)
      } else {
        WorkspaceSectionHeader(
          "Creator Brief",
          subtitle: "A concise read on content, audience, performance, and promotion style.")
        FactSection(title: "Overview", fields: presentation.briefFields)

        DisclosureGroup {
          ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: WorkspaceDesign.spaceM) {
              sourceColumn
              analysisColumn
            }
            .frame(minWidth: 610)

            VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
              sourceColumn
              analysisColumn
            }
          }
          .padding(.top, WorkspaceDesign.spaceS)
        } label: {
          Label("Explore source facts and AI evidence", systemImage: "doc.text.magnifyingglass")
            .font(.headline)
        }
      }

      contactSection
      manualEditor
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
        FactSection(
          title: "AI Analysis — \(section.title)",
          fields: presentation.sections[section] ?? [])
      }
      FactSection(
        title: "AI Inference — Audience",
        fields: presentation.sections[.audienceInference] ?? [])
      FactSection(
        title: "AI Analysis — Promotion Fit",
        fields: presentation.sections[.promotionFit] ?? [])
    }
    .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private var contactSection: some View {
    GroupBox("Contacts") {
      if presentation.contacts.isEmpty {
        Text("Unavailable")
          .foregroundStyle(.secondary)
          .frame(maxWidth: .infinity, alignment: .leading)
      } else {
        VStack(alignment: .leading, spacing: 12) {
          ForEach(Array(presentation.contacts.enumerated()), id: \.offset) { index, contact in
            Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 7) {
              GridRow {
                Text("Email").foregroundStyle(.secondary)
                Text(contact.email).textSelection(.enabled)
              }
              if let purpose = contact.purpose,
                !purpose.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              {
                GridRow {
                  Text("Purpose").foregroundStyle(.secondary)
                  Text(purpose)
                }
              }
              GridRow {
                Text("Availability").foregroundStyle(.secondary)
                Text(contact.availability.displayName)
              }
              GridRow {
                Text("Validation").foregroundStyle(.secondary)
                Text(contact.validationState)
              }
              GridRow {
                Text("Source").foregroundStyle(.secondary)
                if let sourceURL = contact.sourceURL {
                  Link(contact.source, destination: sourceURL)
                } else {
                  Text(contact.source)
                }
              }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if index < presentation.contacts.count - 1 {
              Divider()
            }
          }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
      }
    }
  }

  private var manualEditor: some View {
    GroupBox("Manual Contact") {
      VStack(alignment: .leading, spacing: 10) {
        TextField("Email", text: $manualDraft.email)
          .textContentType(.emailAddress)
          .accessibilityIdentifier("profile.manual.email")

        Text("Notes")
          .font(.caption)
          .foregroundStyle(.secondary)
        TextEditor(text: $manualDraft.notes)
          .frame(minHeight: 100)
          .accessibilityIdentifier("profile.manual.notes")

        HStack {
          if let validationMessage = manualDraft.validationMessage {
            Label(validationMessage, systemImage: "exclamationmark.triangle")
              .foregroundStyle(.red)
          }
          Spacer()
          if isSaving {
            ProgressView().controlSize(.small)
          }
          Button("Save", action: onSave)
            .disabled(
              !ProfileActionPolicy.canSaveManual(
                writesEnabled: writesEnabled,
                isInFlight: isSaving,
                isValid: manualDraft.validationMessage == nil)
            )
            .accessibilityIdentifier("profile.manual.save")
            .help("Save the manual contact and notes")
        }
      }
      .padding(.top, 4)
    }
  }
}
