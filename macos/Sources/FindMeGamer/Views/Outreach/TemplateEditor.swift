import FindMeGamerCore
import SwiftUI
import WebKit

private enum TemplateWorkspaceMode: String, CaseIterable, Identifiable {
  case edit = "Edit"
  case preview = "Preview"

  var id: String { rawValue }
}

struct TemplateEditor: View {
  @Bindable var model: OutreachManagementModel

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var confirmation: Confirmation?
  @State private var workspaceMode = TemplateWorkspaceMode.edit
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
            Picker("Template workspace", selection: workspaceModeSelection) {
              ForEach(TemplateWorkspaceMode.allCases) { mode in
                Text(mode.rawValue).tag(mode)
              }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 220)

            Spacer()

            if model.hasUnsavedTemplateChanges {
              WorkspaceStatusLozenge(
                title: "Unsaved changes",
                systemImage: "pencil.circle.fill",
                tone: .warning)
            }
          }
          .padding(.horizontal, WorkspaceDesign.spaceM)
          .padding(.vertical, WorkspaceDesign.spaceS)

          Divider()

          ZStack {
            workspaceContent
              .id(workspaceMode)
              .transition(
                WorkspaceMotionPolicy.transition(
                  direction: workspaceDirection,
                  role: .switcher,
                  reduceMotion: reduceMotion))
          }
          .frame(maxWidth: .infinity, maxHeight: .infinity)
          .clipped()
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
    switch workspaceMode {
    case .edit:
      editor
    case .preview:
      preview
    }
  }

  private var workspaceModeSelection: Binding<TemplateWorkspaceMode> {
    Binding(
      get: { workspaceMode },
      set: { mode in
        guard mode != workspaceMode else { return }
        workspaceDirection = WorkspaceMotionPolicy.direction(
          from: workspaceMode,
          to: mode,
          ordered: TemplateWorkspaceMode.allCases)
        withAnimation(
          WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)
        ) {
          workspaceMode = mode
        }
      })
  }

  private var editor: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        HStack {
          Text("Template Editor")
            .font(.title2.bold())
          Spacer()
          if model.isTemplateActionInFlight {
            ProgressView()
              .controlSize(.small)
          }
        }

        if model.hasUnsavedTemplateChanges {
          HStack {
            Label("Unsaved changes", systemImage: "pencil.circle")
              .foregroundStyle(.orange)
            Spacer()
            Button("Discard Changes") {
              confirmation = .discard
            }
            .disabled(model.isTemplateActionInFlight)
          }
          .padding(10)
          .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
        }

        field("Name") {
          TextField("Template Name", text: name)
            .textFieldStyle(.roundedBorder)
        }

        field("Subject") {
          TextField("Email Subject", text: subject)
            .textFieldStyle(.roundedBorder)
        }

        VStack(alignment: .leading, spacing: 6) {
          HStack {
            Text("Markdown Body")
              .font(.headline)
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
            .font(.body)
            .frame(minHeight: 220)
            .padding(5)
            .background(.background, in: RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(.separator))
        }

        HStack(spacing: 12) {
          field("Accepted CTA Label") {
            TextField("Accepted CTA Label", text: acceptedLabel)
              .textFieldStyle(.roundedBorder)
          }
          field("Declined CTA Label") {
            TextField("Declined CTA Label", text: declinedLabel)
              .textFieldStyle(.roundedBorder)
          }
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

        HStack {
          Button("Save") {
            confirmation = .save
          }
          .buttonStyle(.borderedProminent)
          .disabled(!writesEnabled || !model.canSaveTemplate)

          Button("Duplicate") {
            Task { await model.duplicateSelectedTemplate() }
          }
          .disabled(!canMutateSavedTemplate)

          Button("Set Default") {
            confirmation = .setDefault
          }
          .disabled(!canMutateSavedTemplate || selectedTemplateIsDefault)

          Spacer()

          Button("Delete", role: .destructive) {
            confirmation = .delete
          }
          .disabled(!canMutateSavedTemplate)
        }
      }
      .padding(18)
    }
    .disabled(model.isTemplateActionInFlight)
  }

  @ViewBuilder private var preview: some View {
    VStack(spacing: 0) {
      HStack {
        Text("Server Preview")
          .font(.headline)
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
        ContentUnavailableView(
          "Save first", systemImage: "square.and.arrow.down",
          description: Text(message))
      case .loading:
        ProgressView("Rendering Preview…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      case .available(let rendered):
        VStack(alignment: .leading, spacing: 0) {
          Text(rendered.subject)
            .font(.headline)
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
        }
      }
    }
  }

  private func field<Content: View>(_ title: String, @ViewBuilder content: () -> Content)
    -> some View
  {
    VStack(alignment: .leading, spacing: 6) {
      Text(title)
        .font(.headline)
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
