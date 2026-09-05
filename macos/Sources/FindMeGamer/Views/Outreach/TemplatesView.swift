import FindMeGamerCore
import SwiftUI

enum TemplateWorkspaceLayout: Equatable {
  case columns(selectorWidth: CGFloat)
  case compact
}

enum TemplateWorkspaceLayoutPolicy {
  static let columnBreakpoint: CGFloat = 880
  static let minimumSelectorWidth: CGFloat = 220
  static let maximumSelectorWidth: CGFloat = 320

  static func layout(for availableWidth: CGFloat) -> TemplateWorkspaceLayout {
    guard availableWidth >= columnBreakpoint else { return .compact }

    let proposedWidth = availableWidth * 0.24
    let selectorWidth = min(
      max(proposedWidth, minimumSelectorWidth),
      maximumSelectorWidth)
    return .columns(selectorWidth: selectorWidth)
  }
}

struct TemplatesView: View {
  @Bindable var model: OutreachManagementModel
  @State private var editorPresentation = TemplateEditorPresentation()

  var body: some View {
    Group {
      if model.isLoadingTemplates && model.templates.isEmpty {
        ProgressView("Loading Templates…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if model.templates.isEmpty && model.templateDraft == nil {
        ContentUnavailableView {
          Label("No Templates", systemImage: "doc.text")
        } description: {
          if let error = model.templatesError { Text(error) }
        } actions: {
          if model.templatesError != nil {
            Button("Try Again") {
              Task { await model.loadTemplates() }
            }
          }
          Button("Create Template") {
            model.beginCreatingTemplate()
          }
        }
      } else {
        GeometryReader { proxy in
          templateWorkspace(
            layout: TemplateWorkspaceLayoutPolicy.layout(for: proxy.size.width)
          )
          .frame(width: proxy.size.width, height: proxy.size.height)
        }
      }
    }
    .task {
      if model.templates.isEmpty && model.templateDraft == nil {
        await model.loadTemplates()
      }
    }
  }

  @ViewBuilder
  private func templateWorkspace(layout: TemplateWorkspaceLayout) -> some View {
    // Keep the editor at the same structural identity when the sidebar or window changes width.
    HStack(spacing: 0) {
      if case .columns(let selectorWidth) = layout {
        templateList
          .frame(width: selectorWidth)
        Divider()
      }
      VStack(spacing: 0) {
        if layout == .compact {
          compactTemplateSelector
          Divider()
        }
        TemplateEditor(model: model, presentation: $editorPresentation)
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
  }

  private var compactTemplateSelector: some View {
    HStack(spacing: 10) {
      Picker("Template", selection: templateSelection) {
        if model.selectedTemplateID == nil {
          Text("New Template")
            .tag(nil as UUID?)
        }

        ForEach(model.templates) { template in
          Text(template.isDefault ? "\(template.name) ★" : template.name)
            .tag(Optional(template.id))
        }
      }
      .pickerStyle(.menu)
      .disabled(model.isTemplateActionInFlight || model.hasUnsavedTemplateChanges)

      Spacer(minLength: 0)

      Button {
        model.beginCreatingTemplate()
      } label: {
        Label("Create Template", systemImage: "plus")
      }
      .help("Create Template")
      .disabled(model.isTemplateActionInFlight || model.hasUnsavedTemplateChanges)
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
  }

  private var templateList: some View {
    VStack(spacing: 0) {
      HStack {
        Text("Templates")
          .font(.system(.headline, design: .rounded))
        Spacer()
        Button {
          model.beginCreatingTemplate()
        } label: {
          Label("Create Template", systemImage: "plus")
        }
        .labelStyle(.iconOnly)
        .help("Create Template")
        .disabled(model.isTemplateActionInFlight || model.hasUnsavedTemplateChanges)
      }
      .padding(16)

      Divider()

      List(selection: templateSelection) {
        ForEach(model.templates) { template in
          HStack(alignment: .top, spacing: 10) {
            Image(systemName: "doc.text")
              .font(.system(size: 17, weight: .light))
              .foregroundStyle(StudioPalette.blue)
              .frame(width: 28, height: 32)
              .background(StudioPalette.blue.opacity(0.08), in: RoundedRectangle(cornerRadius: 7))
              .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 4) {
              Text(template.name)
                .font(.callout.weight(.medium))
                .lineLimit(2)
              Text(template.subjectTemplate)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            }
            Spacer(minLength: 0)
            if template.isDefault {
              Image(systemName: "checkmark.circle")
                .foregroundStyle(.secondary)
                .accessibilityLabel("Default Template")
            }
          }
          .padding(.vertical, 7)
          .tag(template.id)
        }
      }
      .listStyle(.sidebar)
      .scrollContentBackground(.hidden)
      .disabled(model.isTemplateActionInFlight || model.hasUnsavedTemplateChanges)

      if let error = model.templatesError {
        VStack(alignment: .leading, spacing: 8) {
          Label(error, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
            .textSelection(.enabled)
          Button("Try Again") {
            Task { await model.loadTemplates() }
          }
        }
        .font(.caption)
        .padding(12)
      }
    }
  }

  private var templateSelection: Binding<UUID?> {
    Binding(
      get: { model.selectedTemplateID },
      set: { id in
        guard let id else { return }
        model.selectTemplate(id: id)
      })
  }
}
