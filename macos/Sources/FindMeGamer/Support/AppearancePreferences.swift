import FindMeGamerCore
import SwiftUI

struct AppearancePreferences: ViewModifier {
  @AppStorage("appearance-mode") private var appearanceRawValue = AppearanceMode.system.rawValue
  @AppStorage("font-size") private var fontSizeRawValue = FontSizePreference.default.rawValue

  func body(content: Content) -> some View {
    let appearance = AppearanceMode.restoring(rawValue: appearanceRawValue)
    let fontSize = FontSizePreference.restoring(rawValue: fontSizeRawValue)

    content
      .preferredColorScheme(appearance.colorScheme)
      .dynamicTypeSize(fontSize.dynamicTypeSize)
  }
}
