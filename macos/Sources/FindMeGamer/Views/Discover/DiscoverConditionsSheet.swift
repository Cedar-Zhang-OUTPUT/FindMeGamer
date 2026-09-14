import FindMeGamerCore
import SwiftUI

struct DiscoverConditionsSheet: View {
  @Bindable var model: DiscoverModel
  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var languageSearch = ""
  private let languages = [
    "en", "zh", "es", "pt", "fr", "de", "ja", "ko", "ru", "it", "pl", "tr", "ar", "hi", "id", "th",
    "vi", "uk", "nl", "sv",
  ]
  private var selectedLanguages: Set<String> {
    Set(model.conditions.language.split(separator: ",").map(String.init))
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      Text("Discover creators").font(.title2.bold())
      Text(model.selectedGame?.name ?? "Choose a game").foregroundStyle(.secondary)
      Form {
        Section("Platforms") {
          ForEach(model.capabilities) { capability in
            Toggle(
              isOn: Binding(
                get: { model.conditions.platforms.contains(capability.platform) },
                set: { selected in
                  if selected {
                    model.conditions.platforms.insert(capability.platform)
                  } else {
                    model.conditions.platforms.remove(capability.platform)
                  }
                })
            ) {
              HStack {
                Text(capability.title)
                if !capability.available { Text("Unavailable").foregroundStyle(.secondary) }
              }
            }
            .disabled(!capability.available || model.isSubmitting)
            .toggleStyle(.checkbox)
          }
        }
        Section("Content languages") {
          DisclosureGroup(
            selectedLanguages.isEmpty
              ? "Any" : selectedLanguages.sorted().map(languageName).joined(separator: ", ")
          ) {
            Button("Any") { model.conditions.language = "" }
            TextField("Search languages", text: $languageSearch)
            ScrollView {
              VStack(alignment: .leading) {
                ForEach(
                  languages.filter {
                    languageSearch.isEmpty
                      || languageName($0).localizedCaseInsensitiveContains(languageSearch)
                  }, id: \.self
                ) { code in
                  Toggle(
                    languageName(code),
                    isOn: Binding(
                      get: { selectedLanguages.contains(code) },
                      set: { selected in
                        var values = selectedLanguages
                        if selected { values.insert(code) } else { values.remove(code) }
                        model.conditions.language = values.sorted().joined(separator: ",")
                      }))
                }
              }
            }.frame(height: 100)
          }
        }.disabled(model.isSubmitting)
        Section("Followers · Any unless bounds are set") {
          TextField("Minimum (optional)", text: $model.conditions.minimumFollowers)
          TextField("Maximum (optional)", text: $model.conditions.maximumFollowers)
        }.disabled(model.isSubmitting)
        Section("Content Keywords") {
          TextField("Optional keywords", text: $model.conditions.keywords)
        }.disabled(model.isSubmitting)
      }.formStyle(.grouped).frame(height: 390)
      if let error = model.error { Text(error).foregroundStyle(.red).font(.callout) }
      if !model.conditions.isValid {
        Text("Choose a platform and enter a valid follower range.").foregroundStyle(.secondary)
      }
      HStack {
        Button("Cancel") { model.cancelConditions() }.keyboardShortcut(.cancelAction)
        Spacer()
        if model.isSubmitting { ProgressView().controlSize(.small) }
        Button("Submit") { Task { await model.submit() } }
          .keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent)
          .disabled(!model.canSubmitConditions || !writesEnabled)
      }
    }.padding(24).frame(width: 510)
  }
  private func languageName(_ code: String) -> String {
    Locale(identifier: "en").localizedString(forLanguageCode: code) ?? code
  }
}
