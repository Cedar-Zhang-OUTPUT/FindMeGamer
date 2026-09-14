import Foundation
import Observation

@MainActor @Observable public final class DiscoverModel {
  public var gameQuery = ""
  public var steamURL = ""
  public var selectedGame: DiscoverGame?
  public var conditions = DiscoverConditions()
  public private(set) var games: [DiscoverGame] = []
  public private(set) var capabilities: [DiscoverCapability] = []
  public private(set) var history: [DiscoverSummary] = []
  public private(set) var record: DiscoverRecord?
  public private(set) var selectedIDs: Set<UUID> = []
  public private(set) var batches: [DiscoverBatch] = []
  public private(set) var error: String?
  public private(set) var gameError: String?
  public private(set) var isResolving = false
  public private(set) var isLoadingGames = false
  public private(set) var isSubmitting = false
  public private(set) var isSubmittingBatch = false
  public var conditionsPresented = false
  public var analysisConfirmationPresented = false
  @ObservationIgnored private let api: any DiscoverAPIService
  @ObservationIgnored private let idempotencyKey: @Sendable () -> String
  @ObservationIgnored private var createKeys: [CreateIntent: String] = [:]
  @ObservationIgnored private var batchKeys: [BatchIntent: String] = [:]
  @ObservationIgnored private var selections: [UUID: Set<UUID>] = [:]
  @ObservationIgnored private var records: [UUID: DiscoverRecord] = [:]
  @ObservationIgnored private var trackedBatchRecords: Set<UUID> = []
  @ObservationIgnored private var batchCache: [UUID: [DiscoverBatch]] = [:]
  @ObservationIgnored private var batchSubmissionRevisions: [UUID: Int] = [:]
  @ObservationIgnored private var openGeneration = 0

  public init(
    api: any DiscoverAPIService,
    idempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString }
  ) {
    self.api = api
    self.idempotencyKey = idempotencyKey
  }
  public var filteredGames: [DiscoverGame] {
    games.filter { gameQuery.isEmpty || $0.name.localizedCaseInsensitiveContains(gameQuery) }
  }
  public var canStart: Bool { selectedGame != nil && !isResolving && !isSubmitting }
  public var canSubmitConditions: Bool {
    canStart && conditions.isValid
      && conditions.platforms.isSubset(of: Set(capabilities.filter(\.available).map(\.platform)))
  }
  public func load() async {
    async let games: Void = loadGames()
    async let history: Void = loadHistory()
    do {
      let values = try await api.discoverCapabilities()
      guard !Task.isCancelled else { return }
      capabilities = values
    } catch {
      self.error = "Could not load platform availability. Open Settings to check connections."
    }
    _ = await (games, history)
  }
  public func loadGames() async {
    guard !isLoadingGames else { return }
    isLoadingGames = true
    defer { isLoadingGames = false }
    do {
      var loaded: [DiscoverGame] = []
      var cursor: String?
      var seen: Set<String> = []
      repeat {
        let page = try await api.discoverGames(cursor: cursor)
        try Task.checkCancellation()
        loaded.append(
          contentsOf: page.items.filter { game in !loaded.contains { $0.url == game.url } })
        cursor = page.nextCursor
        if let cursor, !seen.insert(cursor).inserted { throw APIError.invalidResponse }
      } while cursor != nil
      games = loaded
      gameError = nil
    } catch is CancellationError {} catch { gameError = "Could not load games. Try again." }
  }
  public func resolveGame() async {
    guard !isResolving else { return }
    let input = steamURL
    isResolving = true
    gameError = nil
    defer { isResolving = false }
    do {
      let game = try await api.resolveDiscoverGame(url: input)
      guard !Task.isCancelled, steamURL == input else { return }
      selectedGame = game
    } catch is CancellationError {} catch {
      gameError = "Could not resolve this Steam URL. Check it and try again."
    }
  }
  public func loadHistory() async {
    do {
      var cursor: String?
      var seen: Set<String> = []
      var loaded: [DiscoverSummary] = []
      repeat {
        let page = try await api.discoverHistory(cursor: cursor)
        try Task.checkCancellation()
        loaded.append(contentsOf: page.items.filter { row in !loaded.contains { $0.id == row.id } })
        cursor = page.nextCursor
        if let cursor, !seen.insert(cursor).inserted { throw APIError.invalidResponse }
      } while cursor != nil
      // A simultaneous accepted submission must not disappear behind an older history response.
      let locallyCreated = history.filter { row in
        records[row.id] != nil && !loaded.contains(where: { $0.id == row.id })
      }
      history = (loaded + locallyCreated).sorted { $0.createdAt > $1.createdAt }
    } catch is CancellationError {} catch {
      self.error = "Could not refresh Discover history. Existing results are still available."
    }
  }
  public func open(id: UUID) async {
    openGeneration += 1
    let generation = openGeneration
    if let current = record { selections[current.id] = selectedIDs }
    if let cached = records[id] {
      record = cached
      selectedIDs = selections[id] ?? []
      batches = batchCache[id] ?? []
    }
    do {
      let value = try await api.discover(id: id)
      guard !Task.isCancelled, generation == openGeneration else { return }
      records[id] = value
      record = value
      selectedIDs = selections[id] ?? []
      error = nil
      await refreshBatches(id: id)
    } catch is CancellationError {} catch {
      if generation == openGeneration { self.error = "Could not load Discover results. Try again." }
    }
  }
  public func selectAll() {
    selectedIDs = Set(record?.candidates.map(\.id) ?? [])
    saveSelection()
  }
  public func retry() async {
    guard let current = record, !current.isActive, !isSubmitting else { return }
    isSubmitting = true
    defer { isSubmitting = false }
    do {
      let value = try await api.retryDiscover(id: current.id)
      try Task.checkCancellation()
      records[value.id] = value
      upsert(value)
      if record?.id == current.id { record = value }
      error = nil
    } catch is CancellationError {} catch {
      self.error =
        "Could not confirm retry. Existing results are retained; retry reuses this Discover record."
    }
  }
  public func deselectAll() {
    selectedIDs.removeAll()
    saveSelection()
  }
  public func toggleCandidate(_ id: UUID) {
    if !selectedIDs.insert(id).inserted { selectedIDs.remove(id) }
    saveSelection()
  }
  private func saveSelection() { if let record { selections[record.id] = selectedIDs } }
  public func presentConditions() { conditionsPresented = true }
  public func cancelConditions() { conditionsPresented = false }
  public func presentAnalysisConfirmation() { analysisConfirmationPresented = true }
  public func cancelAnalysisConfirmation() { analysisConfirmationPresented = false }
  public func submit() async {
    guard canSubmitConditions, let selectedGame else { return }
    let intent = CreateIntent(game: selectedGame, conditions: conditions)
    let key = createKeys[intent] ?? idempotencyKey()
    createKeys[intent] = key
    isSubmitting = true
    error = nil
    defer { isSubmitting = false }
    do {
      let value = try await api.createDiscover(
        game: intent.game, conditions: intent.conditions, idempotencyKey: key)
      guard !Task.isCancelled else { return }
      createKeys[intent] = nil
      conditionsPresented = false
      records[value.id] = value
      record = value
      selectedIDs = []
      batches = []
      upsert(value)
    } catch is CancellationError {} catch {
      self.error = "Could not confirm Discover submission. Retry keeps the same request key."
    }
  }
  public func submitAnalysis(mode: DiscoverAnalysisMode) async {
    guard let record, !selectedIDs.isEmpty, selectedIDs.count <= 100, !isSubmittingBatch else {
      return
    }
    let intent = BatchIntent(recordID: record.id, ids: selectedIDs, mode: mode)
    let key = batchKeys[intent] ?? idempotencyKey()
    batchKeys[intent] = key
    isSubmittingBatch = true
    error = nil
    defer { isSubmittingBatch = false }
    do {
      let batch = try await api.createDiscoverBatch(
        id: intent.recordID, candidateIDs: intent.ids.sorted { $0.uuidString < $1.uuidString },
        mode: intent.mode, idempotencyKey: key)
      guard !Task.isCancelled else { return }
      batchKeys[intent] = nil
      analysisConfirmationPresented = false
      var values = batchCache[intent.recordID] ?? []
      values.removeAll { $0.id == batch.id }
      values.insert(batch, at: 0)
      batchCache[intent.recordID] = values
      batchSubmissionRevisions[intent.recordID, default: 0] += 1
      trackedBatchRecords.insert(intent.recordID)
      if self.record?.id == intent.recordID { batches = values }
    } catch is CancellationError {} catch {
      self.error =
        "Could not confirm analysis. Retry keeps the same selection, mode and request key."
    }
  }
  public func runPolling() async {
    while !Task.isCancelled {
      do { try await Task.sleep(for: .seconds(3)) } catch { return }
      let active = Set(
        records.values.filter(\.isActive).map(\.id)
          + history.filter { $0.status == "queued" || $0.status == "running" }.map(\.id))
      for id in active {
        do {
          let value = try await api.discover(id: id)
          try Task.checkCancellation()
          records[id] = value
          upsert(value)
          if record?.id == id { record = value }
        } catch is CancellationError { return } catch {
          self.error = "Discover refresh failed. Loaded results are retained."
        }
      }
      for id in trackedBatchRecords { await refreshBatches(id: id) }
    }
  }
  private func refreshBatches(id: UUID) async {
    let submissionRevision = batchSubmissionRevisions[id, default: 0]
    do {
      let values = try await api.discoverBatches(id: id)
      try Task.checkCancellation()
      // A pre-submission snapshot must not erase an acknowledged batch or stop its polling.
      guard submissionRevision == batchSubmissionRevisions[id, default: 0] else { return }
      batchCache[id] = values
      if values.contains(where: \.isActive) {
        trackedBatchRecords.insert(id)
      } else {
        trackedBatchRecords.remove(id)
      }
      if record?.id == id { batches = values }
    } catch is CancellationError {} catch {
      self.error = "Could not refresh analysis history. Existing progress is retained."
    }
  }
  private func upsert(_ value: DiscoverRecord) {
    history.removeAll { $0.id == value.id }
    history.insert(
      .init(
        id: value.id, gameName: value.gameName, status: value.status,
        candidateCount: value.candidates.count, createdAt: value.createdAt), at: 0)
  }
}
private struct CreateIntent: Hashable {
  let game: DiscoverGame
  let conditions: DiscoverConditions
}
private struct BatchIntent: Hashable {
  let recordID: UUID
  let ids: Set<UUID>
  let mode: DiscoverAnalysisMode
}
