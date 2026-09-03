import FindMeGamerCore
import SwiftUI

enum LibraryLayout {
  static let headerRowCount = 2
  static let searchMaximumWidth: CGFloat = 360
  static let gridMinimumWidth: CGFloat = 240
  static let gridMaximumWidth: CGFloat = 340
  static let profileTypes: [ProfileType] = [.game, .creator]
}

enum LibraryAccessibility {
  static let profileType = "library.profile-type"
  static let onlyCollection = "library.only-collection"
  static let search = "library.search"
  static let analyzeRequest = "library.analyze-request"
  static let grid = "library.grid"
}

private struct PageRequest: Equatable {
  let profileType: ProfileType
  let query: String
  let onlyCollection: Bool
  let cursor: String
}

struct LibraryView: View {
  @Bindable var model: LibraryModel
  let activeAnalysisJobCount: Int
  let onAnalyzeRequest: () -> Void
  let onOpenProfile: (ProfileCard) -> Void

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var lastPageRequest: PageRequest?

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      LibraryHeader(
        model: model,
        activeAnalysisJobCount: activeAnalysisJobCount,
        writesEnabled: writesEnabled,
        onAnalyzeRequest: onAnalyzeRequest)

      if let error = model.error {
        errorBanner(error)
      }

      libraryContent
    }
    .padding()
    .task {
      model.selectType(model.selectedType)
    }
  }

  @ViewBuilder private var libraryContent: some View {
    if model.items.isEmpty && model.isLoadingFirstPage {
      ProgressView()
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    } else if model.items.isEmpty && model.error == nil {
      ContentUnavailableView(
        LibraryCopy.empty,
        systemImage: model.selectedType == .game ? "gamecontroller" : "person.2"
      )
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    } else {
      ScrollView {
        LazyVGrid(
          columns: [
            GridItem(
              .adaptive(
                minimum: LibraryLayout.gridMinimumWidth,
                maximum: LibraryLayout.gridMaximumWidth),
              spacing: 14)
          ],
          spacing: 14
        ) {
          ForEach(model.items) { item in
            profileCard(item)
          }
        }
        .accessibilityIdentifier(LibraryAccessibility.grid)

        paginationFooter
          .padding(.vertical, 12)
      }
    }
  }

  private func errorBanner(_ error: APIError) -> some View {
    HStack(spacing: 10) {
      Label(error.description, systemImage: "exclamationmark.triangle")
        .foregroundStyle(.secondary)
        .lineLimit(2)
      Spacer()
      Button("Try Again") {
        Task { await model.loadFirstPage() }
      }
      .help("Reload the current profile library")
    }
    .padding(10)
    .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
  }

  @ViewBuilder private func profileCard(_ item: ProfileCard) -> some View {
    switch item {
    case .game(let card):
      GameProfileCard(
        card: card,
        writesEnabled: writesEnabled,
        isUpdatingFavorite: model.favoriteUpdatingIDs.contains(card.id),
        isHighlighted: model.highlightedProfileID == card.id,
        onOpen: { onOpenProfile(item) },
        onFavorite: { Task { await model.toggleFavorite(id: card.id) } })
    case .creator(let card):
      CreatorProfileCard(
        card: card,
        writesEnabled: writesEnabled,
        isUpdatingFavorite: model.favoriteUpdatingIDs.contains(card.id),
        isHighlighted: model.highlightedProfileID == card.id,
        onOpen: { onOpenProfile(item) },
        onFavorite: { Task { await model.toggleFavorite(id: card.id) } })
    }
  }

  @ViewBuilder private var paginationFooter: some View {
    if model.isLoadingNextPage {
      ProgressView()
        .controlSize(.small)
        .frame(maxWidth: .infinity)
    } else if model.canLoadNextPage, let cursor = model.nextCursor {
      Color.clear
        .frame(height: 1)
        .task(id: cursor) {
          await requestNextPage(cursor: cursor)
        }
    }
  }

  @MainActor
  private func requestNextPage(cursor: String) async {
    let request = PageRequest(
      profileType: model.selectedType,
      query: model.query,
      onlyCollection: model.onlyCollection,
      cursor: cursor)
    guard lastPageRequest != request, model.canLoadNextPage else { return }
    lastPageRequest = request
    await model.loadNextPage()
  }
}
