import FindMeGamerCore
import SwiftUI

enum LibraryCopy {
  static let searchPlaceholder = "Search Profiles…"
  static let onlyCollection = "Favorites"
  static let analyzeRequest = "Analyze Profile"
  static let empty = "No profiles found."

  static func profileCount(_ count: Int, type: ProfileType, hasMore: Bool) -> String {
    let noun =
      type == .game
      ? (count == 1 ? "game" : "games")
      : (count == 1 ? "creator" : "creators")
    return "\(count) \(noun)\(hasMore ? " loaded" : "")"
  }
}

enum LibraryBadge {
  static func visibleCount(for count: Int) -> Int? {
    count > 0 ? count : nil
  }
}

struct LibraryHeader: View {
  @Bindable var model: LibraryModel
  let analysisJobCount: Int
  let activeAnalysisJobCount: Int
  let writesEnabled: Bool
  let onSelectProfileType: (ProfileType) -> Void
  let onAnalyzeRequest: () -> Void
  let onAnalysisActivity: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      WorkspacePageHeader(WorkspacePageCopy.library) {
        HStack(spacing: 10) {
          if analysisJobCount > 0 {
            Button(action: onAnalysisActivity) {
              HStack(spacing: 6) {
                if activeAnalysisJobCount > 0 {
                  ProgressView().controlSize(.mini)
                } else {
                  Image(systemName: "clock")
                }
                Text("Activity · \(analysisJobCount)")
              }
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("library.activity")
            .accessibilityLabel("Analysis activity, \(activeAnalysisJobCount) in progress")
          }
          Button(action: onAnalyzeRequest) {
            Label(LibraryCopy.analyzeRequest, systemImage: "plus")
          }
          .buttonStyle(.bordered)
          .controlSize(.large)
          .accessibilityIdentifier(LibraryAccessibility.analyzeRequest)
          .help("Request analysis for a game or creator profile")

        }
      }

      LibraryControlsLayout {
        profilePicker
        searchField
        collectionToggle
      }
      .fixedSize(horizontal: false, vertical: true)
    }
  }

  private var profilePicker: some View {
    Picker(
      "Profile Type",
      selection: Binding(get: { model.selectedType }, set: { onSelectProfileType($0) })
    ) {
      ForEach(LibraryLayout.profileTypes, id: \.self) { type in
        Text(type == .game ? "Games" : "Creators").tag(type)
      }
    }
    .pickerStyle(.segmented)
    .labelsHidden()
    .accessibilityIdentifier(LibraryAccessibility.profileType)
  }

  private var collectionToggle: some View {
    Toggle(
      isOn: Binding(
        get: { model.onlyCollection }, set: { model.setOnlyCollection($0) })
    ) {
      Label(LibraryCopy.onlyCollection, systemImage: "heart")
    }
    .toggleStyle(.button)
    .accessibilityIdentifier(LibraryAccessibility.onlyCollection)
    .help("Show only profiles you have favorited")
  }

  private var searchField: some View {
    HStack(spacing: WorkspaceDesign.spaceS) {
      Image(systemName: "magnifyingglass")
        .foregroundStyle(.secondary)
      TextField(
        LibraryCopy.searchPlaceholder,
        text: Binding(get: { model.query }, set: { model.setSearch($0) })
      )
      .textFieldStyle(.plain)
      .accessibilityLabel("Search profiles")
      .accessibilityIdentifier(LibraryAccessibility.search)
      .help("Search the selected profile library")
      if !model.query.isEmpty {
        Button {
          model.setSearch("")
        } label: {
          Image(systemName: "xmark.circle.fill")
            .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Clear search")
      }
    }
    .padding(.horizontal, 11)
    .padding(.vertical, 8)
    .background(Color(nsColor: .textBackgroundColor), in: RoundedRectangle(cornerRadius: 8))
    .overlay {
      RoundedRectangle(cornerRadius: 8)
        .strokeBorder(Color.primary.opacity(0.08))
        .allowsHitTesting(false)
    }
  }
}
