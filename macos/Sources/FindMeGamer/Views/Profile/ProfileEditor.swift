import FindMeGamerCore
import SwiftUI

struct ProfileEditor: View {
  let type: ProfileType
  let read: () async throws -> ProfileEditDocument
  let save: (ProfileEditPatch) async throws -> ProfileEditDocument
  let onSaved: () -> Void
  @Environment(\.dismiss) private var dismiss
  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var editor: ProfileEditorState?
  @State private var loadError: String?
  @State private var confirmingDiscard = false

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Edit \(type.displayName) profile").font(.title2.bold())
      Text(
        "Edits update the current profile. Existing Match results keep their original snapshots. Contacts and notes are saved separately."
      )
      .font(.caption).foregroundStyle(.secondary)
      if let editor {
        ScrollView {
          VStack(alignment: .leading, spacing: 16) {
            ForEach(["facts", "analysis", "brief"], id: \.self) { section in
              GroupBox(
                section == "facts"
                  ? "Basic information" : section == "analysis" ? "Analysis" : "Brief"
              ) {
                VStack(alignment: .leading, spacing: 16) {
                  ForEach(editor.document.fields.filter { $0.section == section }) { field in
                    fieldEditor(field, editor: editor)
                  }
                }.padding(8).frame(maxWidth: .infinity, alignment: .leading)
              }
            }
          }.padding(.trailing, 4)
        }
        .disabled(editor.isBusy || editor.needsReconciliation || !writesEnabled)
        if let message = editor.message {
          Text(message).font(.callout).foregroundStyle(editor.didSave ? .secondary : .primary)
            .textSelection(.enabled).accessibilityIdentifier("profile.editor.message")
        }
        Divider()
        HStack {
          if editor.isBusy { ProgressView().controlSize(.small) }
          if editor.needsReconciliation {
            Button("Read current profile") {
              Task {
                await editor.reconcile(using: read)
                if editor.didSave { onSaved() }
              }
            }.disabled(editor.isBusy)
          }
          Spacer()
          Button(editor.didSave && !editor.isDirty ? "Done" : "Cancel") { cancel(editor) }
            .keyboardShortcut(.cancelAction).disabled(editor.isBusy)
          Button("Save") {
            Task {
              await editor.save(using: save)
              if editor.didSave { onSaved() }
            }
          }
          .keyboardShortcut("s", modifiers: .command)
          .buttonStyle(.borderedProminent)
          .disabled(!editor.canSave || !writesEnabled)
          .accessibilityIdentifier("profile.editor.save")
        }
      } else {
        Spacer()
        if let loadError {
          Text(loadError)
          Button("Retry") { Task { await load() } }
        } else {
          ProgressView("Loading editable fields…")
        }
        Spacer()
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
      }
    }
    .padding(20)
    .frame(minWidth: 600, idealWidth: 720, minHeight: 580, idealHeight: 720)
    .interactiveDismissDisabled(editor?.isDirty == true || editor?.isBusy == true)
    .task { await load() }
    .confirmationDialog(
      "Discard unsaved profile changes?", isPresented: $confirmingDiscard, titleVisibility: .visible
    ) {
      Button("Discard Changes", role: .destructive) {
        editor?.cancel()
        dismiss()
      }
      Button("Keep Editing", role: .cancel) {}
    } message: {
      Text(
        editor?.needsReconciliation == true
          ? "The last save is not confirmed. Discarding closes this local draft; it cannot undo a save already received by the server."
          : "Local edits will be lost.")
    }
  }

  @ViewBuilder private func fieldEditor(_ field: ProfileEditField, editor: ProfileEditorState)
    -> some View
  {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        Text(field.label + (field.required ? " *" : "")).font(.headline)
        Spacer()
        Text(
          editor.isManual(field)
            ? "Manual" : field.sourceValue == nil ? "No analyzed value" : "Analyzed"
        )
        .font(.caption).foregroundStyle(.secondary)
        if editor.isManual(field) {
          Button("Use analyzed value") { editor.reset(field.key) }.font(.caption)
        }
      }
      let binding = Binding<String>(
        get: { editor.value(for: field.key).text },
        set: { text in
          editor.set(
            field.kind == "list"
              ? .list(text.isEmpty ? [] : text.components(separatedBy: "\n")) : .text(text),
            for: field.key)
        })
      if field.kind == "text" {
        TextField(field.label, text: binding).textFieldStyle(.roundedBorder)
          .accessibilityIdentifier("profile.editor." + field.key)
      } else {
        TextEditor(text: binding).font(.body).frame(minHeight: 64, maxHeight: 120)
          .padding(4).overlay(RoundedRectangle(cornerRadius: 5).stroke(.quaternary))
          .accessibilityLabel(field.label).accessibilityIdentifier("profile.editor." + field.key)
        if field.kind == "list" {
          Text("One item per line. Clear all text for an empty list.").font(.caption)
            .foregroundStyle(.secondary)
        }
      }
      if editor.changes[field.key] != nil {
        Text("Current saved value: " + field.value.text).font(.caption).foregroundStyle(.secondary)
          .textSelection(.enabled)
      }
      if editor.isManual(field) || editor.resetFields.contains(field.key) {
        DisclosureGroup("Analyzed value") {
          Text(field.sourceValue?.text ?? "No analyzed value is available.")
            .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
        }.font(.caption)
      }
    }
  }
  private func cancel(_ editor: ProfileEditorState) {
    if editor.isDirty { confirmingDiscard = true } else { dismiss() }
  }
  private func load() async {
    guard editor == nil else { return }
    loadError = nil
    do { editor = ProfileEditorState(document: try await read()) } catch {
      loadError = "Could not load editable fields. Retry when connected."
    }
  }
}
