import Foundation
import Observation

extension ProfileCard {
  public var profileType: ProfileType {
    switch self {
    case .game: .game
    case .creator: .creator
    }
  }

  public var isFavorite: Bool {
    switch self {
    case .game(let card): card.favorite
    case .creator(let card): card.favorite
    }
  }

  fileprivate func replacingFavorite(with favorite: Bool) -> ProfileCard {
    switch self {
    case .game(let card):
      .game(
        GameProfileCard(
          id: card.id, name: card.name, steamAppID: card.steamAppID,
          canonicalURL: card.canonicalURL, favorite: favorite,
          currentFacts: card.currentFacts, brief: card.brief, sourceStatus: card.sourceStatus,
          lastAnalyzedAt: card.lastAnalyzedAt, nextAnalysisAt: card.nextAnalysisAt))
    case .creator(let card):
      .creator(
        CreatorProfileCard(
          id: card.id, name: card.name, youtubeChannelID: card.youtubeChannelID,
          canonicalURL: card.canonicalURL, favorite: favorite,
          currentFacts: card.currentFacts, brief: card.brief, sourceStatus: card.sourceStatus,
          lastAnalyzedAt: card.lastAnalyzedAt, nextAnalysisAt: card.nextAnalysisAt,
          contact: card.contact))
    }
  }
}

@MainActor
@Observable
public final class LibraryModel {
  private struct FavoriteOverlay {
    var revision: UInt64
    var card: ProfileCard
    var isUpdating: Bool
  }

  private struct TypeState {
    var items: [ProfileCard] = []
    var query = ""
    var onlyCollection = false
    var nextCursor: String?
    var selectedProfileID: UUID?
    var isLoadingFirstPage = false
    var isLoadingNextPage = false
    var favoriteUpdatingIDs: Set<UUID> = []
    var error: APIError?
    var highlightedProfileID: UUID?
    var loaded = false
    var dirty = false
    var pendingReload = false
    var criteriaGeneration: UInt64 = 0
    var listGeneration: UInt64 = 0
    var favoriteRevision: UInt64 = 0
    var favoriteOverlays: [UUID: FavoriteOverlay] = [:]
    var errorGeneration: UInt64 = 0
    var highlightGeneration: UInt64 = 0
  }

  public private(set) var selectedType: ProfileType = .creator

  public var items: [ProfileCard] { currentState.items }
  public var query: String { currentState.query }
  public var onlyCollection: Bool { currentState.onlyCollection }
  public var nextCursor: String? { currentState.nextCursor }
  public var selectedProfileID: UUID? { currentState.selectedProfileID }
  public var isLoadingFirstPage: Bool { currentState.isLoadingFirstPage }
  public var isLoadingNextPage: Bool { currentState.isLoadingNextPage }
  public var favoriteUpdatingIDs: Set<UUID> { currentState.favoriteUpdatingIDs }
  public var error: APIError? { currentState.error }
  public var highlightedProfileID: UUID? { currentState.highlightedProfileID }

  public var canLoadNextPage: Bool {
    nextCursor != nil && !isLoadingFirstPage && !isLoadingNextPage
  }

  @ObservationIgnored private let api: any APIService
  @ObservationIgnored private let clock: any AppClock
  private var states: [ProfileType: TypeState] = [
    .game: TypeState(),
    .creator: TypeState(),
  ]
  @ObservationIgnored private var debounceTasks: [ProfileType: Task<Void, Never>] = [:]
  @ObservationIgnored private var highlightTasks: [ProfileType: Task<Void, Never>] = [:]

  public init(api: any APIService, clock: any AppClock = ContinuousAppClock()) {
    self.api = api
    self.clock = clock
  }

  public func selectType(_ type: ProfileType) {
    selectedType = type
    let state = state(for: type)
    if (!state.loaded || state.dirty) && !state.isLoadingFirstPage {
      scheduleFirstPage(for: type)
    }
  }

  public func selectProfile(id: UUID?) {
    updateState(for: selectedType) { $0.selectedProfileID = id }
  }

  public func clearError() {
    updateState(for: selectedType) {
      $0.errorGeneration &+= 1
      $0.error = nil
    }
  }

  public func setOnlyCollection(_ enabled: Bool) {
    let type = selectedType
    guard state(for: type).onlyCollection != enabled else { return }
    debounceTasks[type]?.cancel()
    debounceTasks[type] = nil
    invalidateList(for: type, clearCursor: true)
    updateState(for: type) {
      $0.onlyCollection = enabled
      $0.criteriaGeneration &+= 1
      $0.pendingReload = true
    }
    scheduleFirstPage(for: type)
  }

  public func setSearch(_ query: String) {
    let type = selectedType
    guard state(for: type).query != query else { return }
    debounceTasks[type]?.cancel()
    invalidateList(for: type, clearCursor: true)
    updateState(for: type) {
      $0.query = query
      $0.criteriaGeneration &+= 1
      $0.pendingReload = true
    }
    let expectedCriteriaGeneration = state(for: type).criteriaGeneration
    let clock = self.clock
    debounceTasks[type] = Task { @MainActor [weak self] in
      do {
        try await clock.sleep(for: .milliseconds(300))
      } catch {
        return
      }
      guard let self,
        self.state(for: type).criteriaGeneration == expectedCriteriaGeneration
      else { return }
      self.debounceTasks[type] = nil
      _ = await self.loadFirstPage(
        for: type, expectedCriteriaGeneration: expectedCriteriaGeneration, skipIfLoading: true)
    }
  }

  public func loadFirstPage() async {
    _ = await loadFirstPage(for: selectedType)
  }

  public func loadNextPage() async {
    let type = selectedType
    let initialState = state(for: type)
    guard let cursor = initialState.nextCursor, !initialState.isLoadingFirstPage,
      !initialState.isLoadingNextPage
    else {
      return
    }

    let generation = initialState.listGeneration
    let query = initialState.query
    let onlyCollection = initialState.onlyCollection
    let favoriteRevisions = initialState.favoriteOverlays.mapValues(\.revision)
    let errorGeneration = initialState.errorGeneration &+ 1
    updateState(for: type) {
      $0.isLoadingNextPage = true
      $0.errorGeneration = errorGeneration
      $0.error = nil
    }
    do {
      let page = try await api.listProfiles(
        type: type, query: query, onlyCollection: onlyCollection, cursor: cursor, limit: 50)
      guard state(for: type).listGeneration == generation else { return }
      updateState(for: type) { state in
        var seen = Set(state.items.map(\.id))
        let items = reconciled(
          page.items, with: state, requestFavoriteRevisions: favoriteRevisions)
        for item in items where seen.insert(item.id).inserted {
          state.items.append(item)
        }
        state.nextCursor = page.nextCursor
        state.isLoadingNextPage = false
        if state.errorGeneration == errorGeneration { state.error = nil }
      }
    } catch {
      guard state(for: type).listGeneration == generation else { return }
      updateState(for: type) {
        $0.isLoadingNextPage = false
        $0.errorGeneration &+= 1
        $0.error = Self.loadError(from: error)
      }
    }
  }

  public func toggleFavorite(id: UUID) async {
    guard let location = favoriteLocation(for: id) else { return }
    let type = location.type
    guard !state(for: type).favoriteUpdatingIDs.contains(id) else { return }
    let original = location.card
    let requestedFavorite = !original.isFavorite
    let optimistic = original.replacingFavorite(with: requestedFavorite)

    if !state(for: type).pendingReload {
      invalidateList(for: type, clearCursor: false)
    }
    updateState(for: type) { state in
      state.favoriteRevision &+= 1
      state.favoriteOverlays[id] = FavoriteOverlay(
        revision: state.favoriteRevision, card: optimistic, isUpdating: true)
      state.favoriteUpdatingIDs.insert(id)
      state.errorGeneration &+= 1
      state.error = nil
      state.items[location.index] = optimistic
    }

    do {
      let canonical = try await api.setFavorite(
        type: type, id: id, favorite: requestedFavorite)
      guard canonical.profileType == type, canonical.id == id else {
        restoreFavoriteFailure(
          id: id, type: type, original: original, originalIndex: location.index,
          optimistic: optimistic)
        return
      }
      updateState(for: type) { state in
        state.favoriteRevision &+= 1
        state.favoriteOverlays[id] = FavoriteOverlay(
          revision: state.favoriteRevision, card: canonical, isUpdating: false)
        state.favoriteUpdatingIDs.remove(id)
        guard let index = state.items.firstIndex(where: { $0.id == id }) else { return }
        if state.onlyCollection && !canonical.isFavorite {
          state.items.remove(at: index)
        } else {
          state.items[index] = canonical
        }
      }
    } catch {
      restoreFavoriteFailure(
        id: id, type: type, original: original, originalIndex: location.index,
        optimistic: optimistic)
    }
  }

  public func consume(jobBatch: JobChangeBatch) async {
    let affected = Set(jobBatch.affectedProfileIDs)
    var idsByType: [ProfileType: [UUID]] = [:]
    for change in jobBatch.changes {
      guard case .analysis(let job) = change, job.status == .succeeded,
        let profileID = job.profileID, affected.contains(profileID)
      else { continue }
      idsByType[job.profileType, default: []].append(profileID)
    }

    for type in ProfileType.allCases where type != selectedType && !(idsByType[type] ?? []).isEmpty
    {
      invalidateList(for: type, clearCursor: false)
      updateState(for: type) { $0.dirty = true }
    }

    let type = selectedType
    guard let affectedIDs = idsByType[type], !affectedIDs.isEmpty else { return }
    guard await loadFirstPage(for: type) else { return }
    let presentIDs = Set(state(for: type).items.map(\.id))
    guard let highlightedID = affectedIDs.last(where: { presentIDs.contains($0) }) else { return }
    showHighlight(highlightedID, for: type)
  }

  private var currentState: TypeState { state(for: selectedType) }

  private func state(for type: ProfileType) -> TypeState {
    states[type] ?? TypeState()
  }

  private func updateState(for type: ProfileType, _ update: (inout TypeState) -> Void) {
    var value = state(for: type)
    update(&value)
    states[type] = value
  }

  private func invalidateList(for type: ProfileType, clearCursor: Bool) {
    updateState(for: type) {
      $0.listGeneration &+= 1
      $0.isLoadingFirstPage = false
      $0.isLoadingNextPage = false
      if clearCursor { $0.nextCursor = nil }
    }
  }

  private func scheduleFirstPage(for type: ProfileType) {
    updateState(for: type) { $0.pendingReload = true }
    let expectedCriteriaGeneration = state(for: type).criteriaGeneration
    Task { @MainActor [weak self] in
      _ = await self?.loadFirstPage(
        for: type, expectedCriteriaGeneration: expectedCriteriaGeneration, skipIfLoading: true)
    }
  }

  private func loadFirstPage(
    for type: ProfileType,
    expectedCriteriaGeneration: UInt64? = nil,
    skipIfLoading: Bool = false
  ) async -> Bool {
    let existing = state(for: type)
    if let expectedCriteriaGeneration,
      existing.criteriaGeneration != expectedCriteriaGeneration
    {
      return false
    }
    if skipIfLoading && existing.isLoadingFirstPage { return false }

    debounceTasks[type]?.cancel()
    debounceTasks[type] = nil
    let generation = existing.listGeneration &+ 1
    let errorGeneration = existing.errorGeneration &+ 1
    updateState(for: type) {
      $0.listGeneration = generation
      $0.isLoadingFirstPage = true
      $0.isLoadingNextPage = false
      $0.errorGeneration = errorGeneration
      $0.error = nil
    }
    let snapshot = state(for: type)
    let favoriteRevisions = snapshot.favoriteOverlays.mapValues(\.revision)

    do {
      let page = try await api.listProfiles(
        type: type, query: snapshot.query, onlyCollection: snapshot.onlyCollection,
        cursor: nil, limit: 50)
      guard state(for: type).listGeneration == generation else { return false }
      updateState(for: type) { state in
        state.items = reconciled(
          page.items, with: state, requestFavoriteRevisions: favoriteRevisions)
        state.nextCursor = page.nextCursor
        state.isLoadingFirstPage = false
        state.loaded = true
        state.dirty = false
        state.pendingReload = false
        if state.errorGeneration == errorGeneration { state.error = nil }
      }
      return true
    } catch {
      guard state(for: type).listGeneration == generation else { return false }
      updateState(for: type) {
        $0.isLoadingFirstPage = false
        $0.pendingReload = false
        $0.errorGeneration &+= 1
        $0.error = Self.loadError(from: error)
      }
      return false
    }
  }

  private func favoriteLocation(for id: UUID) -> (type: ProfileType, index: Int, card: ProfileCard)?
  {
    let types = [selectedType] + ProfileType.allCases.filter { $0 != selectedType }
    for type in types {
      let items = state(for: type).items
      if let index = items.firstIndex(where: { $0.id == id }) {
        return (type, index, items[index])
      }
    }
    return nil
  }

  private func restoreFavoriteFailure(
    id: UUID, type: ProfileType, original: ProfileCard, originalIndex: Int,
    optimistic: ProfileCard
  ) {
    updateState(for: type) { state in
      state.favoriteRevision &+= 1
      state.favoriteOverlays[id] = FavoriteOverlay(
        revision: state.favoriteRevision, card: original, isUpdating: false)
      state.favoriteUpdatingIDs.remove(id)
      if let currentIndex = state.items.firstIndex(where: { $0.id == id }),
        state.items[currentIndex] == optimistic
      {
        state.items.remove(at: currentIndex)
        state.items.insert(original, at: min(originalIndex, state.items.count))
      }
      state.errorGeneration &+= 1
      state.error = Self.favoriteError()
    }
  }

  private func reconciled(
    _ items: [ProfileCard], with state: TypeState,
    requestFavoriteRevisions: [UUID: UInt64]
  ) -> [ProfileCard] {
    items.compactMap { item in
      guard let overlay = state.favoriteOverlays[item.id],
        overlay.isUpdating || requestFavoriteRevisions[item.id] != overlay.revision
      else { return item }
      if state.onlyCollection && !overlay.isUpdating && !overlay.card.isFavorite {
        return nil
      }
      return overlay.card
    }
  }

  private func showHighlight(_ id: UUID, for type: ProfileType) {
    highlightTasks[type]?.cancel()
    let token = state(for: type).highlightGeneration &+ 1
    updateState(for: type) {
      $0.highlightGeneration = token
      $0.highlightedProfileID = id
    }
    let clock = self.clock
    highlightTasks[type] = Task { @MainActor [weak self] in
      do {
        try await clock.sleep(for: .seconds(2))
      } catch {
        return
      }
      guard let self, self.state(for: type).highlightGeneration == token else { return }
      self.updateState(for: type) { $0.highlightedProfileID = nil }
      self.highlightTasks[type] = nil
    }
  }

  private static func loadError(from error: any Error) -> APIError {
    APIError(
      code: "profile_list_failed", message: "Could not load profiles.", retryable: true,
      correlationID: (error as? APIError)?.correlationID)
  }

  private static func favoriteError() -> APIError {
    APIError(
      code: "favorite_update_failed", message: "Could not update favorite.", retryable: true)
  }
}
