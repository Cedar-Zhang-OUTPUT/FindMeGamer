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

  var body: some View {
    Group {
      if model.isLoadingTemplates && model.templates.isEmpty {
        ProgressView("Loading Templates…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if model.templates.isEmpty && model.templateDraft == nil {
        ContentUnavailableView {
          Label("No Templates", systemImage: "doc.text")
        } description: {
          Text(model.templatesError ?? "Create a Template to start writing outreach.")
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
    switch layout {
    case .columns(let selectorWidth):
      HStack(spacing: 0) {
        templateList
          .frame(width: selectorWidth)

        Divider()

        TemplateEditor(model: model)
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    case .compact:
      VStack(spacing: 0) {
        compactTemplateSelector

        Divider()

        TemplateEditor(model: model)
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
          .font(.headline)
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
      .padding(12)

      Divider()

      List(selection: templateSelection) {
        ForEach(model.templates) { template in
          HStack {
            Text(template.name)
              .lineLimit(1)
            Spacer()
            if template.isDefault {
              Image(systemName: "star.fill")
                .foregroundStyle(.yellow)
                .accessibilityLabel("Default Template")
            }
          }
          .tag(template.id)
        }
      }
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
