import FindMeGamerCore
import SwiftUI

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
        HSplitView {
          templateList
            .frame(minWidth: 220, idealWidth: 260, maxWidth: 340)
          TemplateEditor(model: model)
            .frame(minWidth: 620, idealWidth: 820)
        }
      }
    }
    .task {
      if model.templates.isEmpty && model.templateDraft == nil {
        await model.loadTemplates()
      }
    }
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
        .disabled(model.isTemplateActionInFlight)
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
      .disabled(model.isTemplateActionInFlight)

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
