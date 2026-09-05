import FindMeGamerCore
import SwiftUI

struct AppearanceSettings: View {
  @Bindable var model: SettingsModel

  var body: some View {
    Section("Appearance") {
      LazyVGrid(columns: [GridItem(.adaptive(minimum: 94, maximum: 150), spacing: 12)], spacing: 12)
      {
        ForEach(AppearanceMode.allCases, id: \.self) { mode in
          Button {
            model.setAppearanceMode(mode)
          } label: {
            VStack(spacing: 8) {
              appearancePreview(mode)
                .frame(height: 68)
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .overlay {
                  RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(
                      model.appearanceMode == mode ? StudioPalette.blue : StudioPalette.line,
                      lineWidth: model.appearanceMode == mode ? 2 : 1)
                }
              HStack(spacing: 5) {
                Image(systemName: model.appearanceMode == mode ? "checkmark.circle.fill" : "circle")
                  .foregroundStyle(model.appearanceMode == mode ? StudioPalette.blue : .secondary)
                Text(mode.title).foregroundStyle(.primary)
              }
              .font(.body)
            }
            .contentShape(Rectangle())
          }
          .buttonStyle(.plain)
          .accessibilityElement(children: .ignore)
          .accessibilityLabel("\(mode.title) appearance")
          .accessibilityAddTraits(model.appearanceMode == mode ? .isSelected : [])
          .accessibilityIdentifier("settings.appearance.\(mode.rawValue)")
        }
      }
      .padding(.vertical, 8)

      Picker("Font Size", selection: fontSize) {
        ForEach(FontSizePreference.allCases, id: \.self) { size in
          Text(size.title).tag(size)
        }
      }
      HStack(spacing: 12) {
        Image(systemName: "textformat.size").foregroundStyle(.secondary)
        Text("Find Me Gamer").font(.body)
      }
      .accessibilityLabel("Text size preview")
      .padding(.vertical, 6)

      Button("Restore Defaults") {
        model.restoreAppearanceDefaults()
      }
    }
  }

  private func appearancePreview(_ mode: AppearanceMode) -> some View {
    HStack(spacing: 0) {
      previewHalf(isDark: mode == .dark)
      previewHalf(isDark: mode != .light)
    }
    .accessibilityHidden(true)
  }

  private func previewHalf(isDark: Bool) -> some View {
    VStack(alignment: .leading, spacing: 5) {
      Capsule().fill(StudioPalette.blue).frame(width: 24, height: 4)
      RoundedRectangle(cornerRadius: 3)
        .fill(isDark ? Color.white.opacity(0.18) : Color.black.opacity(0.08))
        .frame(height: 18)
      Capsule().fill(isDark ? Color.white.opacity(0.35) : Color.black.opacity(0.18))
        .frame(height: 3)
    }
    .padding(9)
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background(isDark ? Color(red: 0.12, green: 0.15, blue: 0.20) : Color.white)
  }

  private var fontSize: Binding<FontSizePreference> {
    Binding(
      get: { model.fontSize },
      set: { model.setFontSize($0) })
  }
}
