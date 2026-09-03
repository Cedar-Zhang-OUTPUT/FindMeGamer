import FindMeGamerCore
import SwiftUI

struct AppearanceSettings: View {
  @Bindable var model: SettingsModel

  var body: some View {
    Section("Appearance") {
      Picker("Color Mode", selection: appearanceMode) {
        ForEach(AppearanceMode.allCases, id: \.self) { mode in
          Text(mode.title).tag(mode)
        }
      }

      Picker("Font Size", selection: fontSize) {
        ForEach(FontSizePreference.allCases, id: \.self) { size in
          Text(size.title).tag(size)
        }
      }

      Button("Restore Defaults") {
        model.restoreAppearanceDefaults()
      }
    }
  }

  private var appearanceMode: Binding<AppearanceMode> {
    Binding(
      get: { model.appearanceMode },
      set: { model.setAppearanceMode($0) })
  }

  private var fontSize: Binding<FontSizePreference> {
    Binding(
      get: { model.fontSize },
      set: { model.setFontSize($0) })
  }
}
