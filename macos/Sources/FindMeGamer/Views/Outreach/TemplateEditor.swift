import FindMeGamerCore
import SwiftUI
import WebKit

enum TemplateWorkspaceMode: String, CaseIterable, Identifiable {
  case edit = "Edit"
  case preview = "Preview"

  var id: String { rawValue }
}

struct TemplateEditorPresentation {
  var mode = TemplateWorkspaceMode.edit
  var showsResponseLabels = false
}

struct TemplateEditor: View {
  @Bindable var model: OutreachManagementModel
  @Binding var presentation: TemplateEditorPresentation

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var confirmation: Confirmation?
  @State private var workspaceDirection = WorkspaceMotionDirection.stationary

  var body: some View {
    Group {
      if model.templateDraft == nil {
        ContentUnavailableView(
          "Select a Template", systemImage: "doc.text",
          description: Text("Choose a Template from the list or create a new one."))
      } else {
        VStack(spacing: 0) {
          HStack(spacing: WorkspaceDesign.spaceM) {
            Image(systemName: "square.and.pencil")
              .font(.system(size: 17, weight: .light))
              .foregroundStyle(StudioPalette.blue)
              .accessibilityHidden(true)
            Picker("Template workspace", selection: workspaceModeSelection) {
              ForEach(TemplateWorkspaceMode.allCases) { mode in
                Text(mode.rawValue).tag(mode)
              }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 190)

            Spacer()

            if model.hasUnsavedTemplateChanges {
              Label("Draft", systemImage: "circle.fill")
                .font(.caption)
                .foregroundStyle(StudioPalette.amber)
                .help("Unsaved changes")
                .accessibilityLabel("Draft, unsaved changes")
            }
          }
          .padding(.horizontal, WorkspaceDesign.spaceM)
          .padding(.vertical, WorkspaceDesign.spaceS)
          .fixedSize(horizontal: false, vertical: true)

          Divider()

          ZStack {
            workspaceContent
              .id(presentation.mode)
              .transition(
                WorkspaceMotionPolicy.transition(
                  direction: workspaceDirection,
                  role: .switcher,
                  reduceMotion: reduceMotion))
          }
          .frame(maxWidth: .infinity, maxHeight: .infinity)
          .clipped()

          Divider()
          editorActions
        }
      }
    }
    .confirmationDialog(
      confirmation?.title ?? "Confirm Template change",
      isPresented: confirmationPresented,
      titleVisibility: .visible
    ) {
      if let confirmation {
        Button(confirmation.buttonTitle, role: confirmation.role) {
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

  @ViewBuilder private var workspaceContent: some View {
    switch presentation.mode {
    case .edit:
      editor
    case .preview:
      preview
    }
  }

  private var workspaceModeSelection: Binding<TemplateWorkspaceMode> {
    Binding(
      get: { presentation.mode },
      set: { mode in
        guard mode != presentation.mode else { return }
        workspaceDirection = WorkspaceMotionPolicy.direction(
          from: presentation.mode,
          to: mode,
          ordered: TemplateWorkspaceMode.allCases)
        withAnimation(
          WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)
        ) {
          presentation.mode = mode
        }
      })
  }

  private var editor: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        field("Template name") {
          TextField("Template Name", text: name)
            .textFieldStyle(OutreachDraftFieldStyle())
        }

        field("Subject") {
          TextField("Email Subject", text: subject)
            .font(.system(.title3, design: .rounded, weight: .medium))
            .textFieldStyle(OutreachDraftFieldStyle())
        }

        VStack(alignment: .leading, spacing: 6) {
          HStack {
            Text("Message")
              .font(.callout.weight(.medium))
            Spacer()
            Menu("Insert Variable") {
              ForEach(OutreachManagementModel.allowedVariables, id: \.self) { variable in
                Button(variable) {
                  model.insertVariable(variable)
                }
              }
            }
          }
          TextEditor(text: bodyMarkdown)
            .accessibilityLabel("Template Message")
            .font(.system(size: 15))
            .lineSpacing(5)
            .scrollContentBackground(.hidden)
            .frame(minHeight: 260)
            .padding(16)
            .modifier(OutreachWritingSurface())
        }

        DisclosureGroup("Response button labels", isExpanded: $presentation.showsResponseLabels) {
          VStack(alignment: .leading, spacing: 12) {
            Text("These two buttons are included in every email and track the creator’s response.")
              .font(.caption)
              .foregroundStyle(.secondary)
            field("Accept label") {
              TextField("Accepted CTA Label", text: acceptedLabel)
                .textFieldStyle(OutreachDraftFieldStyle())
            }
            field("Decline label") {
              TextField("Declined CTA Label", text: declinedLabel)
                .textFieldStyle(OutreachDraftFieldStyle())
            }
          }
          .padding(.top, 10)
        }

        if !model.templateValidationMessages.isEmpty {
          VStack(alignment: .leading, spacing: 4) {
            ForEach(model.templateValidationMessages, id: \.self) { message in
              Label(message, systemImage: "exclamationmark.circle")
            }
          }
          .font(.caption)
          .foregroundStyle(.red)
        }

        if let error = model.templateActionError {
          Label(error, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
            .textSelection(.enabled)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        }

      }
      .frame(maxWidth: 760, alignment: .leading)
      .padding(24)
      .frame(maxWidth: .infinity)
    }
    .background(StudioPalette.canvas)
    .disabled(model.isTemplateActionInFlight)
  }

  private var editorActions: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 12) {
        templateActionsMenu
        Spacer(minLength: 4)
        discardButton
        saveButton
      }
      VStack(alignment: .leading, spacing: 12) {
        HStack {
          templateActionsMenu
          Spacer(minLength: 4)
          discardButton
        }
        HStack {
          Spacer(minLength: 0)
          saveButton
        }
      }
    }
    .fixedSize(horizontal: false, vertical: true)
    .padding(16)
    .background(StudioPalette.surface.opacity(0.65))
  }

  private var templateActionsMenu: some View {
    Menu("Template actions") {
      Button("Duplicate") { Task { await model.duplicateSelectedTemplate() } }
        .disabled(!canMutateSavedTemplate)
      Button("Set Default") { confirmation = .setDefault }
        .disabled(!canMutateSavedTemplate || selectedTemplateIsDefault)
      Divider()
      Button("Delete", role: .destructive) { confirmation = .delete }
        .disabled(!canMutateSavedTemplate)
    }
    .fixedSize()
  }

  @ViewBuilder private var discardButton: some View {
    if model.hasUnsavedTemplateChanges {
      Button("Discard Changes") { confirmation = .discard }
        .disabled(model.isTemplateActionInFlight)
    }
  }

  private var saveButton: some View {
    HStack(spacing: 8) {
      if model.isTemplateActionInFlight {
        ProgressView().controlSize(.small)
      }
      Button("Save Template") { confirmation = .save }
        .buttonStyle(.borderedProminent)
        .disabled(!writesEnabled || !model.canSaveTemplate)
    }
  }

  @ViewBuilder private var preview: some View {
    VStack(spacing: 0) {
      HStack {
        Text("Server Preview")
          .font(.callout.weight(.medium))
        Image(systemName: "envelope.open")
          .foregroundStyle(StudioPalette.blue)
          .accessibilityHidden(true)
        Spacer()
      }
      .padding(12)
      Divider()

      switch model.previewState {
      case .idle:
        ContentUnavailableView(
          "No Preview", systemImage: "envelope.open",
          description: Text("Select a saved Template to preview it."))
      case .saveFirst(let message):
        ContentUnavailableView {
          Label("Save first", systemImage: "square.and.arrow.down")
        } description: {
          Text(message)
        } actions: {
          Button("Return to editing") { presentation.mode = .edit }
        }
      case .loading:
        ProgressView("Rendering Preview…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      case .available(let rendered):
        VStack(alignment: .leading, spacing: 0) {
          Text(rendered.subject)
            .font(.system(.title3, design: .rounded, weight: .medium))
            .textSelection(.enabled)
            .padding(12)
          Divider()
          RenderedHTMLPreview(html: rendered.html)
        }
      case .failed(let message):
        ContentUnavailableView {
          Label("Preview unavailable", systemImage: "exclamationmark.triangle")
        } description: {
          Text(message)
        } actions: {
          Button("Try Again") { model.retryTemplatePreview() }
            .disabled(model.isTemplateActionInFlight)
          Button("Return to editing") { presentation.mode = .edit }
        }
      }
    }
  }

  private func field<Content: View>(_ title: String, @ViewBuilder content: () -> Content)
    -> some View
  {
    VStack(alignment: .leading, spacing: 6) {
      Text(title)
        .font(.callout.weight(.medium))
      content()
    }
  }

  private var name: Binding<String> {
    Binding(
      get: { model.templateDraft?.name ?? "" },
      set: { model.editTemplateName($0) })
  }

  private var subject: Binding<String> {
    Binding(
      get: { model.templateDraft?.subjectTemplate ?? "" },
      set: { model.editTemplateSubject($0) })
  }

  private var bodyMarkdown: Binding<String> {
    Binding(
      get: { model.templateDraft?.bodyMarkdown ?? "" },
      set: { model.editTemplateBody($0) })
  }

  private var acceptedLabel: Binding<String> {
    Binding(
      get: { model.templateDraft?.acceptedLabel ?? "" },
      set: { model.editAcceptedLabel($0) })
  }

  private var declinedLabel: Binding<String> {
    Binding(
      get: { model.templateDraft?.declinedLabel ?? "" },
      set: { model.editDeclinedLabel($0) })
  }

  private var selectedTemplateIsDefault: Bool {
    model.templates.first(where: { $0.id == model.selectedTemplateID })?.isDefault == true
  }

  private var canMutateSavedTemplate: Bool {
    writesEnabled && model.selectedTemplateID != nil && !model.isTemplateActionInFlight
      && !model.hasUnsavedTemplateChanges
  }

  private var confirmationPresented: Binding<Bool> {
    Binding(
      get: { confirmation != nil },
      set: { if !$0 { confirmation = nil } })
  }

  private func perform(_ action: Confirmation) {
    confirmation = nil
    Task {
      switch action {
      case .save:
        await model.saveTemplate()
      case .setDefault:
        await model.setSelectedTemplateDefault()
      case .delete:
        await model.deleteSelectedTemplate()
      case .discard:
        model.discardTemplateChanges()
      }
    }
  }

  private enum Confirmation {
    case save
    case setDefault
    case delete
    case discard

    var title: String {
      switch self {
      case .save: "Save shared Template?"
      case .setDefault: "Change the default Template?"
      case .delete: "Delete this shared Template?"
      case .discard: "Discard unsaved changes?"
      }
    }

    var buttonTitle: String {
      switch self {
      case .save: "Save"
      case .setDefault: "Set Default"
      case .delete: "Delete"
      case .discard: "Discard Changes"
      }
    }

    var message: String {
      switch self {
      case .save: "Coworkers will see the saved Template changes."
      case .setDefault: "New outreach will use this Template by default."
      case .delete: "This cannot be undone. The server may refuse deletion of a required Template."
      case .discard: "Your unsaved Template edits will be replaced by the saved version."
      }
    }

    var role: ButtonRole? {
      self == .delete || self == .discard ? .destructive : nil
    }
  }
}

private struct RenderedHTMLPreview: NSViewRepresentable {
  let html: String

  func makeCoordinator() -> Coordinator {
    Coordinator()
  }

  func makeNSView(context: Context) -> WKWebView {
    let configuration = WKWebViewConfiguration()
    configuration.websiteDataStore = .nonPersistent()
    configuration.defaultWebpagePreferences.allowsContentJavaScript = false
    configuration.preferences.javaScriptCanOpenWindowsAutomatically = false

    let webView = WKWebView(frame: .zero, configuration: configuration)
    webView.navigationDelegate = context.coordinator
    return webView
  }

  func updateNSView(_ webView: WKWebView, context: Context) {
    guard context.coordinator.loadedHTML != html else { return }
    context.coordinator.loadedHTML = html
    webView.loadHTMLString(html, baseURL: nil)
  }

  final class Coordinator: NSObject, WKNavigationDelegate {
    var loadedHTML: String?

    func webView(
      _ webView: WKWebView,
      decidePolicyFor navigationAction: WKNavigationAction,
      decisionHandler: @escaping @MainActor @Sendable (WKNavigationActionPolicy) -> Void
    ) {
      let isInitialDocument =
        navigationAction.navigationType == .other
        && navigationAction.request.url?.scheme == "about"
      decisionHandler(isInitialDocument ? .allow : .cancel)
    }
  }
}
