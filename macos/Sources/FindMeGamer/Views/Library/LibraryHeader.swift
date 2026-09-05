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
  let onSelectProfileType: (ProfileType) -> Void
  let onAnalyzeRequest: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      WorkspacePageHeader(WorkspacePageCopy.library) {
        HStack(spacing: WorkspaceDesign.spaceS) {
          if let count = LibraryBadge.visibleCount(for: activeAnalysisJobCount) {
            WorkspaceStatusLozenge(
              title: "\(count) active",
              systemImage: "waveform.path.ecg",
              tone: .accent)
          }

          Button(action: onAnalyzeRequest) {
            Label(LibraryCopy.analyzeRequest, systemImage: "sparkles")
          }
          .buttonStyle(.borderedProminent)
          .controlSize(.large)
          .disabled(!writesEnabled)
          .accessibilityIdentifier(LibraryAccessibility.analyzeRequest)
          .help("Request analysis for a game or creator profile")
        }
      }

      WorkspaceSurface(style: .quiet) {
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
          HStack(spacing: WorkspaceDesign.spaceM) {
            Picker(
              "Profile Type",
              selection: Binding(
                get: { model.selectedType },
                set: { onSelectProfileType($0) })
            ) {
              ForEach(LibraryLayout.profileTypes, id: \.self) { type in
                Text("\(type.displayName) Profiles").tag(type)
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
          }

          HStack(spacing: WorkspaceDesign.spaceS) {
            Image(systemName: "magnifyingglass")
              .foregroundStyle(.secondary)

            TextField(
              LibraryCopy.searchPlaceholder,
              text: Binding(
                get: { model.query },
                set: { model.setSearch($0) })
            )
            .textFieldStyle(.plain)
            .frame(maxWidth: LibraryLayout.searchMaximumWidth)
            .accessibilityLabel("Search profiles")
            .accessibilityIdentifier(LibraryAccessibility.search)
            .help("Search the selected profile library")

            Spacer()
          }
          .padding(.horizontal, 11)
          .padding(.vertical, 8)
          .background(
            Color(nsColor: .textBackgroundColor).opacity(0.72),
            in: RoundedRectangle(cornerRadius: 9, style: .continuous)
          )
          .overlay {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
              .strokeBorder(Color.primary.opacity(0.08))
          }
        }
        .padding(WorkspaceDesign.spaceM)
      }
    }
  }
}
