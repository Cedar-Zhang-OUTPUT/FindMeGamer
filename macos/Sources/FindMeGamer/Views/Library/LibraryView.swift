import FindMeGamerCore
import SwiftUI

enum LibraryLayout {
  static let headerRowCount = 2
  static let searchMaximumWidth: CGFloat = 360
  static let gridMinimumWidth = WorkspaceDesign.libraryGridMinimumWidth
  static let gridMaximumWidth = WorkspaceDesign.libraryGridMaximumWidth
  static let profileTypes: [ProfileType] = [.game, .creator]
}

enum LibraryAccessibility {
  static let profileType = "library.profile-type"
  static let onlyCollection = "library.only-collection"
  static let search = "library.search"
  static let analyzeRequest = "library.analyze-request"
  static let grid = "library.grid"
}

enum LibraryContentPresentation: Equatable {
  case initialLoading
  case empty
  case scrollable(showEmptyState: Bool)
}

enum LibraryContentPolicy {
  static func presentation(
    itemCount: Int,
    isLoadingFirstPage: Bool,
    hasError: Bool,
    hasNextCursor: Bool,
    isLoadingNextPage: Bool,
    keepsPaginationHost: Bool
  ) -> LibraryContentPresentation {
    if itemCount > 0 { return .scrollable(showEmptyState: false) }
    if hasNextCursor || isLoadingNextPage || keepsPaginationHost {
      return .scrollable(showEmptyState: true)
    }
    if isLoadingFirstPage { return .initialLoading }
    if hasError { return .scrollable(showEmptyState: false) }
    return .empty
  }
}

struct LibraryPaginationRequest: Hashable, Sendable {
  let profileType: ProfileType
  let query: String
  let onlyCollection: Bool
  let cursor: String
}

struct LibraryPaginationObservation: Equatable, Sendable {
  let request: LibraryPaginationRequest?
  let canLoadNextPage: Bool
  let isLoadingFirstPage: Bool
  let isLoadingNextPage: Bool
  let hasError: Bool
}

struct LibraryPaginationTaskID: Hashable, Sendable {
  let request: LibraryPaginationRequest
  let revision: UInt64
}

enum LibraryRetryAction: Equatable {
  case firstPage
  case nextPage
}

enum LibraryRetryPolicy {
  static func action(
    failedRequest: LibraryPaginationRequest?, current: LibraryPaginationRequest?
  ) -> LibraryRetryAction {
    failedRequest != nil && failedRequest == current ? .nextPage : .firstPage
  }
}

@MainActor
@Observable
final class LibraryPaginationCoordinator {
  private(set) var revision: UInt64 = 0
  private(set) var failedRequest: LibraryPaginationRequest?

  private var activeRequest: LibraryPaginationRequest?
  private var lastAttemptedTaskID: LibraryPaginationTaskID?
  private var pendingReplacement: LibraryPaginationRequest?
  private var queuedRequest: LibraryPaginationRequest?
  private var wasLoadingFirstPage = false
  private var requestBeforeFirstPage: LibraryPaginationRequest?

  var keepsPaginationHost: Bool {
    activeRequest != nil || pendingReplacement != nil || queuedRequest != nil
      || failedRequest != nil
  }

  func taskID(for request: LibraryPaginationRequest) -> LibraryPaginationTaskID {
    LibraryPaginationTaskID(request: request, revision: revision)
  }

  func observe(_ observation: LibraryPaginationObservation) {
    if let activeRequest,
      observation.request == activeRequest,
      observation.canLoadNextPage,
      !observation.isLoadingNextPage,
      !observation.hasError
    {
      pendingReplacement = activeRequest
    }

    if !wasLoadingFirstPage, observation.isLoadingFirstPage {
      requestBeforeFirstPage = observation.request
      failedRequest = nil
    }

    if wasLoadingFirstPage,
      !observation.isLoadingFirstPage,
      requestBeforeFirstPage == observation.request,
      lastAttemptedTaskID?.request == observation.request,
      observation.canLoadNextPage,
      !observation.hasError
    {
      failedRequest = nil
      revision &+= 1
    }
    if wasLoadingFirstPage, !observation.isLoadingFirstPage {
      requestBeforeFirstPage = nil
    }
    wasLoadingFirstPage = observation.isLoadingFirstPage

    if failedRequest != observation.request, observation.request != nil {
      failedRequest = nil
    }
  }

  func retry(_ request: LibraryPaginationRequest) {
    guard failedRequest == request else { return }
    failedRequest = nil
    revision &+= 1
  }

  func run(
    taskID: LibraryPaginationTaskID,
    load: @MainActor () async -> Void,
    current: @MainActor () -> LibraryPaginationObservation
  ) async {
    guard activeRequest == nil else {
      queuedRequest = taskID.request
      return
    }
    guard lastAttemptedTaskID != taskID else { return }

    activeRequest = taskID.request
    lastAttemptedTaskID = taskID
    await load()

    let observation = current()
    activeRequest = nil
    if observation.hasError, observation.request == taskID.request {
      failedRequest = taskID.request
    } else if failedRequest == taskID.request {
      failedRequest = nil
    }

    let shouldReplaceInvalidatedRequest = pendingReplacement == taskID.request
    pendingReplacement = nil
    let shouldStartQueuedRequest = queuedRequest == observation.request
    queuedRequest = nil
    if shouldReplaceInvalidatedRequest || shouldStartQueuedRequest,
      observation.request != nil,
      observation.canLoadNextPage,
      !observation.hasError
    {
      revision &+= 1
    }
  }
}

struct LibraryView: View {
  @Bindable var model: LibraryModel
  @Bindable var analyzeModel: AnalyzeRequestModel
  let onOpenAnalyze: (AnalyzeWorkspacePhase) -> Void
  let onOpenProfile: (ProfileType, UUID) -> Void

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var pagination = LibraryPaginationCoordinator()
  @State private var profileTypeDirection = WorkspaceMotionDirection.stationary

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
      LibraryHeader(
        model: model,
        activeAnalysisJobCount: analyzeModel.activeJobCount,
        writesEnabled: writesEnabled,
        onSelectProfileType: selectProfileType,
        onAnalyzeRequest: { onOpenAnalyze(.request) },
        onAnalysisActivity: { onOpenAnalyze(.activity) })

      if let error = model.error {
        errorBanner(error)
      }

      ZStack {
        libraryContent
          .id(model.selectedType)
          .transition(
            WorkspaceMotionPolicy.transition(
              direction: profileTypeDirection,
              role: .switcher,
              reduceMotion: reduceMotion))
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
      .clipped()
    }
    .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
    .padding(.vertical, WorkspaceDesign.pageVerticalPadding)
    .workspaceCanvas()
    .task {
      model.selectType(model.selectedType)
    }
    .onChange(of: paginationObservation, initial: true) { _, observation in
      pagination.observe(observation)
    }
  }

  private func selectProfileType(_ type: ProfileType) {
    guard type != model.selectedType else { return }
    profileTypeDirection = WorkspaceMotionPolicy.direction(
      from: model.selectedType,
      to: type,
      ordered: LibraryLayout.profileTypes)
    withAnimation(
      WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)
    ) {
      model.selectType(type)
    }
  }

  @ViewBuilder private var libraryContent: some View {
    switch contentPresentation {
    case .initialLoading:
      ProgressView("Loading profiles…")
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    case .empty:
      emptyState
    case .scrollable(let showEmptyState):
      ScrollView {
        LazyVStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
          HStack {
            Text(
              LibraryCopy.profileCount(
                model.items.count, type: model.selectedType, hasMore: model.nextCursor != nil)
            )
            .font(.caption)
            .foregroundStyle(.secondary)
            Spacer()
            if model.isLoadingFirstPage {
              ProgressView().controlSize(.small)
                .accessibilityLabel("Refreshing profiles")
            }
          }

          if showEmptyState {
            if model.error == nil {
              emptyState.frame(minHeight: 220)
            }
          }

          LazyVGrid(
            columns: [
              GridItem(
                .adaptive(
                  minimum: LibraryLayout.gridMinimumWidth,
                  maximum: LibraryLayout.gridMaximumWidth),
                spacing: WorkspaceDesign.spaceM)
            ],
            alignment: .leading,
            spacing: WorkspaceDesign.spaceM
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
      .scrollIndicators(.automatic)
    }
  }

  private var emptyState: some View {
    let context = LibraryEmptyContext.resolve(
      query: model.query, onlyCollection: model.onlyCollection)
    return ContentUnavailableView {
      Label(context.title, systemImage: context == .search ? "magnifyingglass" : "square.stack")
    } description: {
      Text(context.detail)
    } actions: {
      Button(context.actionTitle) {
        switch context {
        case .search: model.setSearch("")
        case .favorites: model.setOnlyCollection(false)
        case .firstProfile: onOpenAnalyze(.request)
        }
      }
      .buttonStyle(.borderedProminent)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
  }

  private var contentPresentation: LibraryContentPresentation {
    LibraryContentPolicy.presentation(
      itemCount: model.items.count,
      isLoadingFirstPage: model.isLoadingFirstPage,
      hasError: model.error != nil,
      hasNextCursor: model.nextCursor != nil,
      isLoadingNextPage: model.isLoadingNextPage,
      keepsPaginationHost: pagination.keepsPaginationHost)
  }

  private func errorBanner(_ error: APIError) -> some View {
    HStack(spacing: 10) {
      Label(error.description, systemImage: "exclamationmark.triangle")
        .foregroundStyle(.secondary)
        .lineLimit(2)
      Spacer()
      Button("Try Again") {
        switch LibraryRetryPolicy.action(
          failedRequest: pagination.failedRequest,
          current: paginationObservation.request)
        {
        case .nextPage:
          if let request = paginationObservation.request {
            pagination.retry(request)
          }
        case .firstPage:
          Task { await model.loadFirstPage() }
        }
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
        onOpen: { onOpenProfile(item.profileType, item.id) },
        onFavorite: { Task { await model.toggleFavorite(id: card.id) } })
    case .creator(let card):
      CreatorProfileCard(
        card: card,
        writesEnabled: writesEnabled,
        isUpdatingFavorite: model.favoriteUpdatingIDs.contains(card.id),
        isHighlighted: model.highlightedProfileID == card.id,
        onOpen: { onOpenProfile(item.profileType, item.id) },
        onFavorite: { Task { await model.toggleFavorite(id: card.id) } })
    }
  }

  @ViewBuilder private var paginationFooter: some View {
    if let request = paginationObservation.request {
      let taskID = pagination.taskID(for: request)
      ZStack {
        if model.isLoadingNextPage {
          ProgressView()
            .controlSize(.small)
        } else {
          Color.clear
        }
      }
      .frame(maxWidth: .infinity, minHeight: 1)
      .task(id: taskID) {
        guard model.canLoadNextPage, pagination.failedRequest != request else { return }
        await pagination.run(
          taskID: taskID,
          load: { await model.loadNextPage() },
          current: { paginationObservation })
      }
    }
  }

  private var paginationObservation: LibraryPaginationObservation {
    LibraryPaginationObservation(
      request: model.nextCursor.map {
        LibraryPaginationRequest(
          profileType: model.selectedType,
          query: model.query,
          onlyCollection: model.onlyCollection,
          cursor: $0)
      },
      canLoadNextPage: model.canLoadNextPage,
      isLoadingFirstPage: model.isLoadingFirstPage,
      isLoadingNextPage: model.isLoadingNextPage,
      hasError: model.error != nil)
  }
}
