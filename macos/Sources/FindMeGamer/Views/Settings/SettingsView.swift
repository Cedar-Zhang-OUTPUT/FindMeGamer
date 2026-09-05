import FindMeGamerCore
import SwiftUI

struct SettingsView: View {
  @Bindable var model: SettingsModel
  @SceneStorage("settings-category") private var categoryRawValue = SettingsCategory.appearance
    .rawValue
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
      WorkspacePageHeader(WorkspacePageCopy.settings)

      GeometryReader { geometry in
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
          if geometry.size.width < 760 {
            Picker("Settings category", selection: categorySelection) {
              ForEach(SettingsCategory.allCases, id: \.self) { category in
                Label(category.title, systemImage: category.systemImage).tag(category)
              }
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("settings.category")
          }
          // Keep the form in one structural location while its navigation adapts.
          // Reparenting it at this breakpoint resets disclosure and input focus.
          HStack(alignment: .top, spacing: WorkspaceDesign.spaceL) {
            if geometry.size.width >= 760 {
              categoryNavigation
                .frame(width: 176)
              Divider()
            }
            selectedContent
          }
        }
      }
      .frame(maxWidth: 1_140, maxHeight: .infinity, alignment: .topLeading)
    }
    .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
    .padding(.vertical, WorkspaceDesign.pageVerticalPadding)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .workspaceCanvas()
    .navigationTitle("Settings")
    .task {
      await model.loadConnections()
      await model.loadReanalysis()
      await model.loadProfileActivity()
    }
  }

  private var categoryNavigation: some View {
    VStack(alignment: .leading, spacing: 4) {
      ForEach(SettingsCategory.allCases, id: \.self) { item in
        Button {
          withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion))
          {
            categoryRawValue = item.rawValue
          }
        } label: {
          HStack(spacing: 10) {
            Image(systemName: item.systemImage)
              .font(.system(size: 13, weight: .semibold))
              .frame(width: 30, height: 30)
              .foregroundStyle(category == item ? StudioPalette.blue : Color.secondary)
              .background(
                StudioPalette.blue.opacity(category == item ? 0.11 : 0.035),
                in: RoundedRectangle(cornerRadius: 9))
            Text(item.title)
            Spacer(minLength: 0)
          }
          .font(.system(.body, weight: category == item ? .semibold : .regular))
          .padding(.horizontal, 12)
          .padding(.vertical, 11)
          .background {
            if category == item {
              RoundedRectangle(cornerRadius: 13).fill(StudioPalette.surface)
                .shadow(color: StudioPalette.ink.opacity(0.045), radius: 8, y: 3)
            }
          }
          .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(category == item ? .isSelected : [])
        .accessibilityIdentifier("settings.category.\(item.rawValue)")
      }
    }
  }

  private var category: SettingsCategory {
    SettingsCategory(rawValue: categoryRawValue) ?? .appearance
  }

  private var categorySelection: Binding<SettingsCategory> {
    Binding(get: { category }, set: { categoryRawValue = $0.rawValue })
  }

  private var selectedContent: some View {
    Form {
      switch category {
      case .appearance: AppearanceSettings(model: model)
      case .connections: ConnectionsSettings(model: model)
      case .reanalysis: ReanalysisSettings(model: model)
      case .workspace: WorkspaceSettings(model: model)
      }
    }
    .formStyle(.grouped)
    .scrollContentBackground(.hidden)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
  }
}

private enum SettingsCategory: String, CaseIterable {
  case appearance, connections, reanalysis, workspace

  var title: String {
    switch self {
    case .appearance: "Appearance"
    case .connections: "Connections"
    case .reanalysis: "Auto-refresh"
    case .workspace: "Workspace"
    }
  }

  var systemImage: String {
    switch self {
    case .appearance: "paintpalette"
    case .connections: "point.3.connected.trianglepath.dotted"
    case .reanalysis: "arrow.triangle.2.circlepath"
    case .workspace: "desktopcomputer"
    }
  }
}
