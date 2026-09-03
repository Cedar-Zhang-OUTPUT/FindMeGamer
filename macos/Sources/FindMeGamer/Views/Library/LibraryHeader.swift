import FindMeGamerCore
import SwiftUI

enum LibraryCopy {
  static let searchPlaceholder = "Search Profiles…"
  static let onlyCollection = "Only Collection"
  static let analyzeRequest = "Analyze Request"
  static let empty = "No profiles found."
}

enum LibraryBadge {
  static func visibleCount(for count: Int) -> Int? {
    count > 0 ? count : nil
  }
}

struct LibraryHeader: View {
  @Bindable var model: LibraryModel
  let activeAnalysisJobCount: Int
  let writesEnabled: Bool
  let onAnalyzeRequest: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(spacing: 12) {
        Picker(
          "Profile Type",
          selection: Binding(
            get: { model.selectedType },
            set: { model.selectType($0) })
        ) {
          ForEach(LibraryLayout.profileTypes, id: \.self) { type in
            Text(type.displayName).tag(type)
          }
        }
        .pickerStyle(.segmented)
        .fixedSize()
        .accessibilityIdentifier(LibraryAccessibility.profileType)

        Toggle(
          LibraryCopy.onlyCollection,
          isOn: Binding(
            get: { model.onlyCollection },
            set: { model.setOnlyCollection($0) })
        )
        .toggleStyle(.checkbox)
        .accessibilityIdentifier(LibraryAccessibility.onlyCollection)

        Spacer()

        if let count = LibraryBadge.visibleCount(for: activeAnalysisJobCount) {
          Text(count, format: .number)
            .font(.caption.bold())
            .padding(.horizontal, 7)
            .padding(.vertical, 3)
            .background(.tint.opacity(0.15), in: Capsule())
            .accessibilityLabel("\(count) active analysis jobs")
        }

        Button(LibraryCopy.analyzeRequest, action: onAnalyzeRequest)
          .disabled(!writesEnabled)
          .accessibilityIdentifier(LibraryAccessibility.analyzeRequest)
          .help("Request analysis for a game or creator profile")
      }

      HStack {
        TextField(
          LibraryCopy.searchPlaceholder,
          text: Binding(
            get: { model.query },
            set: { model.setSearch($0) })
        )
        .textFieldStyle(.roundedBorder)
        .frame(maxWidth: LibraryLayout.searchMaximumWidth)
        .accessibilityLabel("Search profiles")
        .accessibilityIdentifier(LibraryAccessibility.search)
        .help("Search the selected profile library")

        Spacer()
      }
    }
  }
}
