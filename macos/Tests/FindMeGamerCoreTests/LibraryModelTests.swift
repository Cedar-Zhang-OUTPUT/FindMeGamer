import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct LibraryModelTests {
  @MainActor
  @Test func creatorPagesReplaceRatherThanAccumulateAndSupportDirectJumps() async {
    let catalog = (0..<1_200).map { creatorCard(UUID(), name: "Creator \($0)") }
    let api = LibraryAPI(listOutcomes: [
      .page(ProfileCardPage(items: Array(catalog[0..<20]), nextCursor: "2", page: 1, totalCount: 1200, totalPages: 60)),
      .page(ProfileCardPage(items: Array(catalog[20..<40]), nextCursor: "3", page: 2, totalCount: 1200, totalPages: 60)),
      .page(ProfileCardPage(items: Array(catalog[1180..<1200]), nextCursor: nil, page: 60, totalCount: 1200, totalPages: 60)),
      .page(ProfileCardPage(items: Array(catalog[0..<20]), nextCursor: "2", page: 1, totalCount: 1200, totalPages: 60)),
    ])
    let model = LibraryModel(api: api, clock: ManualClock())

    await model.loadFirstPage()
    for _ in 0..<20 { await Task.yield() }
    #expect(model.items == Array(catalog[0..<20]))
    #expect(await api.listCallCount == 1)

    await model.loadNextPage()
    for _ in 0..<20 { await Task.yield() }
    #expect(model.items == Array(catalog[20..<40]))
    #expect(await api.listCallCount == 2)

    await model.loadCreatorPage(60)
    #expect(model.items == Array(catalog[1180..<1200]))
    #expect(model.currentPage == 60)
    #expect(!model.canLoadNextPage)
    await model.loadNextPage()
    #expect(await api.listCallCount == 3)
    await model.loadCreatorPage(1)
    #expect(model.items == Array(catalog[0..<20]))
    #expect(await api.requestedPages == [1, 2, 60, 1])
  }

  @MainActor
  @Test func selectingDefaultUnloadedTypeSchedulesItsFirstPage() async {
    let api = LibraryAPI(listOutcomes: [.page(page([], cursor: nil))])
    let model = LibraryModel(api: api, clock: ManualClock())

    model.selectType(.creator)

    #expect(await eventually { await api.listCallCount == 1 })
    #expect(await eventually { !model.isLoadingFirstPage })
  }

  @MainActor
  @Test func jobRefreshDuringNewSearchUsesFirstPageNotOldPage() async {
    let id = UUID()
    let card = creatorCard(id, name: "Creator")
    let api = LibraryAPI(listOutcomes: [
      .page(ProfileCardPage(items: [card], nextCursor: "2", page: 1, totalCount: 120, totalPages: 6)),
      .page(ProfileCardPage(items: [card], nextCursor: "6", page: 5, totalCount: 120, totalPages: 6)),
      .page(ProfileCardPage(items: [card], nextCursor: "2", page: 1, totalCount: 120, totalPages: 6)),
    ])
    let clock = ManualClock()
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()
    await model.loadCreatorPage(5)
    model.setSearch("new query")
    await model.consume(jobBatch: JobChangeBatch(
      changes: [.analysis(analysisJob(type: .creator, status: .succeeded, profileID: id))],
      affectedProfileIDs: [id], affectedMatchTaskIDs: [], affectedGameIDs: [], hasActiveJobs: false))
    #expect(await api.requestedPages == [1, 5, 1])
    #expect(model.currentPage == 1 && model.query == "new query")
  }

  @MainActor
  @Test func failedPageKeepsVisibleItemsAndRetryTargetsThatPage() async {
    let first = creatorCard(UUID(), name: "First")
    let second = creatorCard(UUID(), name: "Second")
    let api = LibraryAPI(listOutcomes: [
      .page(ProfileCardPage(items: [first], nextCursor: "2", page: 1, totalCount: 21, totalPages: 2)),
      .failure(APIError.invalidResponse),
      .page(ProfileCardPage(items: [second], nextCursor: nil, page: 2, totalCount: 21, totalPages: 2)),
      .page(ProfileCardPage(items: [first], nextCursor: nil, page: 1, totalCount: 1, totalPages: 1)),
    ])
    let model = LibraryModel(api: api, clock: ManualClock())
    await model.loadFirstPage()
    await model.loadCreatorPage(2)
    #expect(model.items == [first])
    #expect(model.currentPage == 1)
    #expect(model.error != nil)
    await model.reloadCurrentPage()
    #expect(model.items == [second])
    #expect(model.currentPage == 2)
    model.setOnlyCollection(true)
    #expect(await eventually { model.items == [first] && model.currentPage == 1 })
    #expect(await api.requestedPages == [1, 2, 2, 1])
  }

  @MainActor
  @Test func defaultCreatorLoadAndTypeSwitchPreserveIndependentState() async {
    let clock = ManualClock()
    let creatorID = UUID(uuidString: "00000000-0000-0000-0000-000000000101")!
    let gameID = UUID(uuidString: "00000000-0000-0000-0000-000000000102")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([creatorCard(creatorID, name: "Creator One")], cursor: "creator-next")),
        .page(page([gameCard(gameID, name: "Game One")], cursor: "game-next")),
        .page(page([gameCard(gameID, name: "Searched Game")], cursor: "game-search-next")),
        .page(page([creatorCard(creatorID, name: "Creator One")], cursor: "creator-filtered")),
      ])
    let model = LibraryModel(api: api, clock: clock)

    await model.loadFirstPage()
    model.selectProfile(id: creatorID)
    model.selectType(.game)
    #expect(await eventually { await api.listCallCount == 2 })
    #expect(await eventually { model.items.map(\.id) == [gameID] })
    model.setSearch("game query")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(300))
    #expect(await eventually { await api.listCallCount == 3 })
    #expect(await eventually { model.nextCursor == "game-search-next" })
    model.selectProfile(id: gameID)

    model.selectType(.creator)
    #expect(model.items.map(\.id) == [creatorID])
    #expect(model.nextCursor == "creator-next")
    #expect(model.selectedProfileID == creatorID)
    model.setOnlyCollection(true)
    #expect(await eventually { await api.listCallCount == 4 })
    #expect(await eventually { model.nextCursor == "creator-filtered" })

    model.selectType(.game)
    #expect(model.items.map(\.id) == [gameID])
    #expect(model.nextCursor == "game-search-next")
    #expect(model.selectedProfileID == gameID)
    #expect(model.query == "game query")
    #expect(!model.onlyCollection)

    let calls = await api.listCalls
    #expect(
      calls[0] == ListCall(type: .creator, query: "", onlyCollection: false, cursor: nil, limit: 20)
    )
    #expect(
      calls[1] == ListCall(type: .game, query: "", onlyCollection: false, cursor: nil, limit: 50))
    #expect(
      calls[2]
        == ListCall(type: .game, query: "game query", onlyCollection: false, cursor: nil, limit: 50)
    )
    #expect(
      calls[3] == ListCall(type: .creator, query: "", onlyCollection: true, cursor: nil, limit: 20))
  }

  @MainActor
  @Test func searchDebouncesExactlyAndUsesLatestQueryAndFilter() async {
    let clock = ManualClock()
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([], cursor: nil)),
        .page(page([creatorCard(UUID(), name: "Latest")], cursor: nil)),
      ])
    let model = LibraryModel(api: api, clock: clock)

    model.setOnlyCollection(true)
    #expect(await eventually { await api.listCallCount == 1 })
    #expect(await eventually { !model.isLoadingFirstPage })

    model.setSearch("first")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    model.setSearch("latest")
    #expect(await eventually { await clock.cancellationCount == 1 })
    #expect(await eventually { await clock.pendingSleepCount == 1 })

    await clock.advance(by: .milliseconds(299))
    await Task.yield()
    #expect(await api.listCallCount == 1)
    await clock.advance(by: .milliseconds(1))
    #expect(await eventually { await api.listCallCount == 2 })

    let call = await api.listCalls[1]
    #expect(
      call
        == ListCall(type: .creator, query: "latest", onlyCollection: true, cursor: nil, limit: 20))
  }

  @MainActor
  @Test func searchInvalidatesAnAlreadyScheduledImmediateLoad() async {
    let clock = ManualClock()
    let api = LibraryAPI(listOutcomes: [.page(page([], cursor: nil))])
    let model = LibraryModel(api: api, clock: clock)

    model.selectType(.game)
    model.setSearch("debounced game")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    for _ in 0..<20 { await Task.yield() }
    #expect(await api.listCallCount == 0)

    await clock.advance(by: .milliseconds(300))
    #expect(await eventually { await api.listCallCount == 1 })
    #expect(
      await api.listCalls == [
        ListCall(
          type: .game, query: "debounced game", onlyCollection: false, cursor: nil, limit: 50)
      ])
  }

  @MainActor
  @Test func staleFirstPageSuccessCannotOverwriteNewerSearchState() async {
    let oldGate = CompletionGate<ProfileCardPage>()
    let clock = ManualClock()
    let oldID = UUID(uuidString: "00000000-0000-0000-0000-000000000201")!
    let newID = UUID(uuidString: "00000000-0000-0000-0000-000000000202")!
    let api = LibraryAPI(
      listOutcomes: [
        .gated(oldGate),
        .page(page([creatorCard(newID, name: "New")], cursor: "new-cursor")),
      ])
    let model = LibraryModel(api: api, clock: clock)

    let oldLoad = Task { await model.loadFirstPage() }
    await oldGate.waitUntilEntered()
    model.setSearch("newest")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(300))
    #expect(await eventually { model.items.map(\.id) == [newID] })

    oldGate.resume(.success(page([creatorCard(oldID, name: "Old")], cursor: "old-cursor")))
    await oldLoad.value

    #expect(model.items.map(\.id) == [newID])
    #expect(model.nextCursor == "new-cursor")
    #expect(model.error == nil)
    #expect(!model.isLoadingFirstPage)
  }

  @MainActor
  @Test func staleFailureIsIgnoredAndCurrentFailurePreservesItemsCursorAndCorrelation() async {
    let oldGate = CompletionGate<ProfileCardPage>()
    let clock = ManualClock()
    let oldID = UUID(uuidString: "00000000-0000-0000-0000-000000000211")!
    let newID = UUID(uuidString: "00000000-0000-0000-0000-000000000212")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([creatorCard(oldID, name: "Initial")], cursor: "initial-cursor")),
        .gated(oldGate),
        .page(page([creatorCard(newID, name: "New")], cursor: "new-cursor")),
        .failure(
          APIError(
            code: "server_error", message: "unsafe server detail", retryable: true,
            correlationID: "safe-correlation")),
      ])
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()

    let staleLoad = Task { await model.loadFirstPage() }
    await oldGate.waitUntilEntered()
    model.setSearch("new")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(300))
    #expect(await eventually { model.items.map(\.id) == [newID] })
    oldGate.resume(
      .failure(
        APIError(
          code: "stale", message: "must not surface", retryable: true,
          correlationID: "stale-correlation")))
    await staleLoad.value

    #expect(model.error == nil)
    await model.loadFirstPage()
    #expect(model.items.map(\.id) == [newID])
    #expect(model.nextCursor == "new-cursor")
    #expect(model.error?.message == "Could not load profiles.")
    #expect(model.error?.correlationID == "safe-correlation")
    #expect(!model.isLoadingFirstPage)
  }

  @MainActor
  @Test func creatorPageNavigationIsSingleFlightAndEndsAtLastPage() async {
    let nextGate = CompletionGate<ProfileCardPage>()
    let firstID = UUID(uuidString: "00000000-0000-0000-0000-000000000301")!
    let secondID = UUID(uuidString: "00000000-0000-0000-0000-000000000302")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([creatorCard(firstID, name: "First")], cursor: "opaque==cursor")),
        .gated(nextGate),
      ])
    let model = LibraryModel(api: api, clock: ManualClock())
    await model.loadFirstPage()

    let firstNext = Task { await model.loadNextPage() }
    await nextGate.waitUntilEntered()
    await model.loadNextPage()
    #expect(await api.listCallCount == 2)

    nextGate.resume(
      .success(
        page(
          [creatorCard(firstID, name: "Duplicate"), creatorCard(secondID, name: "Second")],
          cursor: nil)))
    await firstNext.value

    #expect(model.items.map(\.id) == [firstID, secondID])
    #expect(model.nextCursor == nil)
    #expect(!model.canLoadNextPage)
    await model.loadNextPage()
    #expect(await api.listCallCount == 2)
    #expect(await api.requestedPages == [1, 2])
  }

  @MainActor
  @Test func favoriteIsOptimisticSingleFlightAndAcceptsMatchingCanonicalCard() async throws {
    let gate = CompletionGate<ProfileCard>()
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000401")!
    let contacts = [
      CreatorContact(
        email: "partnerships@example.test", availability: .manual, source: "manual",
        sourceURL: nil, validationState: "valid", purpose: "Partnerships"),
      CreatorContact(
        email: "press@example.test", availability: .discovered,
        source: "public_web_research", sourceURL: "https://example.test/contact",
        validationState: "unverified", purpose: "Press"),
    ]
    let original = creatorCard(id, name: "Original", favorite: false, contacts: contacts)
    let canonical = creatorCard(id, name: "Canonical", favorite: true, contacts: contacts)
    let api = LibraryAPI(
      listOutcomes: [.page(page([original], cursor: "keep-cursor"))],
      favoriteOutcomes: [.gated(gate)])
    let model = LibraryModel(api: api, clock: ManualClock())
    await model.loadFirstPage()

    let update = Task { await model.toggleFavorite(id: id) }
    await gate.waitUntilEntered()
    #expect(model.items.first?.isFavorite == true)
    guard case .creator(let optimisticCard) = try #require(model.items.first) else {
      Issue.record("Expected a Creator card")
      return
    }
    #expect(optimisticCard.contact == contacts.first)
    #expect(optimisticCard.contacts == contacts)
    #expect(model.favoriteUpdatingIDs == [id])
    await model.toggleFavorite(id: id)
    #expect(await api.favoriteCallCount == 1)

    gate.resume(.success(canonical))
    await update.value

    #expect(model.items == [canonical])
    #expect(model.favoriteUpdatingIDs.isEmpty)
    #expect(model.nextCursor == "keep-cursor")
    #expect(await api.favoriteCalls == [FavoriteCall(type: .creator, id: id, favorite: true)])
  }

  @MainActor
  @Test func confirmedUnfavoriteRemovesCardFromOnlyCollection() async {
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000402")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(ProfileCardPage(items: [creatorCard(id, name: "Favorite", favorite: true)], nextCursor: nil, page: 2, totalCount: 21, totalPages: 2)),
        .page(ProfileCardPage(items: [], nextCursor: nil, page: 1, totalCount: 20, totalPages: 1)),
      ],
      favoriteOutcomes: [.card(creatorCard(id, name: "Favorite", favorite: false))])
    let model = LibraryModel(api: api, clock: ManualClock())
    model.setOnlyCollection(true)
    #expect(await eventually { model.items.map(\.id) == [id] })

    await model.toggleFavorite(id: id)

    #expect(model.items.isEmpty)
    #expect(model.currentPage == 1)
    #expect(model.totalCount == 20)
    #expect(await api.requestedPages == [1, 2])
    #expect(model.error == nil)
  }

  @MainActor
  @Test func favoriteFencesAnAlreadyStartedListCompletion() async {
    let oldListGate = CompletionGate<ProfileCardPage>()
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000403")!
    let original = creatorCard(id, name: "Original", favorite: false)
    let canonical = creatorCard(id, name: "Canonical", favorite: true)
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([original], cursor: "cursor")),
        .gated(oldListGate),
      ],
      favoriteOutcomes: [.card(canonical)])
    let model = LibraryModel(api: api, clock: ManualClock())
    await model.loadFirstPage()

    let staleList = Task { await model.loadFirstPage() }
    await oldListGate.waitUntilEntered()
    await model.toggleFavorite(id: id)
    oldListGate.resume(.success(page([original], cursor: "stale-cursor")))
    await staleList.value

    #expect(model.items == [canonical])
    #expect(model.items.first?.isFavorite == true)
    #expect(model.nextCursor == "cursor")
  }

  @MainActor
  @Test(arguments: [FavoriteBadCompletion.failure, .mismatched])
  func favoriteFailureRestoresExactCardOrderAndPreservesControls(
    completion: FavoriteBadCompletion
  ) async {
    let firstID = UUID(uuidString: "00000000-0000-0000-0000-000000000411")!
    let targetID = UUID(uuidString: "00000000-0000-0000-0000-000000000412")!
    let lastID = UUID(uuidString: "00000000-0000-0000-0000-000000000413")!
    let original = creatorCard(targetID, name: "Target", favorite: false)
    let outcome: FavoriteOutcome =
      completion == .failure
      ? .failure(APIError(code: "server_error", message: "unsafe", retryable: true))
      : .card(creatorCard(UUID(), name: "Wrong", favorite: true))
    let api = LibraryAPI(
      listOutcomes: [
        .page(
          page(
            [creatorCard(firstID, name: "First"), original, creatorCard(lastID, name: "Last")],
            cursor: "preserved-cursor"))
      ],
      favoriteOutcomes: [outcome])

    let clock = ManualClock()
    let model = LibraryModel(api: api, clock: clock)
    model.setSearch("preserved query")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(300))
    #expect(await eventually { model.items.map(\.id) == [firstID, targetID, lastID] })

    await model.toggleFavorite(id: targetID)

    #expect(model.items.map(\.id) == [firstID, targetID, lastID])
    #expect(model.items[1] == original)
    #expect(model.nextCursor == "preserved-cursor")
    #expect(model.query == "preserved query")
    #expect(model.error?.message == "Could not update favorite.")
    #expect(model.favoriteUpdatingIDs.isEmpty)
  }

  @MainActor
  @Test func favoriteFailureStillRollsBackWhileANewSearchIsDebouncing() async {
    let favoriteGate = CompletionGate<ProfileCard>()
    let clock = ManualClock()
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000414")!
    let original = creatorCard(id, name: "Target", favorite: false)
    let api = LibraryAPI(
      listOutcomes: [.page(page([original], cursor: "old-cursor"))],
      favoriteOutcomes: [.gated(favoriteGate)])
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()

    let update = Task { await model.toggleFavorite(id: id) }
    await favoriteGate.waitUntilEntered()
    #expect(model.items.first?.isFavorite == true)
    model.setSearch("new query")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    favoriteGate.resume(
      .failure(APIError(code: "server_error", message: "unsafe", retryable: true)))
    await update.value

    #expect(model.items == [original])
    #expect(model.query == "new query")
    #expect(model.nextCursor == nil)
    #expect(model.error?.message == "Could not update favorite.")
  }

  @MainActor
  @Test func pendingSearchSurvivesFavoriteSuccessAndKeepsCanonicalCard() async {
    let favoriteGate = CompletionGate<ProfileCard>()
    let clock = ManualClock()
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000421")!
    let original = creatorCard(id, name: "Target", favorite: false)
    let canonical = creatorCard(id, name: "Canonical Target", favorite: true)
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([original], cursor: "old-cursor")),
        .page(page([original], cursor: "latest-cursor")),
      ],
      favoriteOutcomes: [.gated(favoriteGate)])
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()

    model.setSearch("latest query")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    let update = Task { await model.toggleFavorite(id: id) }
    await favoriteGate.waitUntilEntered()
    await clock.advance(by: .milliseconds(299))
    await Task.yield()
    #expect(await api.listCallCount == 1)
    await clock.advance(by: .milliseconds(1))
    let reloadStarted = await eventually { await api.listCallCount == 2 }
    #expect(reloadStarted)
    guard reloadStarted else {
      favoriteGate.resume(.success(canonical))
      await update.value
      return
    }

    #expect(model.items.first?.isFavorite == true)
    favoriteGate.resume(.success(canonical))
    await update.value

    #expect(model.items == [canonical])
    #expect(model.query == "latest query")
    #expect(model.nextCursor == "latest-cursor")
    #expect(model.error == nil)
    #expect(await api.favoriteCallCount == 1)
    #expect(
      await api.listCalls[1]
        == ListCall(
          type: .creator, query: "latest query", onlyCollection: false, cursor: nil, limit: 20)
    )
  }

  @MainActor
  @Test func pendingSearchSurvivesFavoriteFailureAndKeepsRollbackErrorAfterReload() async {
    let favoriteGate = CompletionGate<ProfileCard>()
    let reloadGate = CompletionGate<ProfileCardPage>()
    let clock = ManualClock()
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000422")!
    let original = creatorCard(id, name: "Target", favorite: false)
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([original], cursor: "old-cursor")),
        .gated(reloadGate),
      ],
      favoriteOutcomes: [.gated(favoriteGate)])
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()

    model.setSearch("failure query")
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    let update = Task { await model.toggleFavorite(id: id) }
    await favoriteGate.waitUntilEntered()
    await clock.advance(by: .milliseconds(300))
    let reloadStarted = await eventually { await api.listCallCount == 2 }
    #expect(reloadStarted)
    guard reloadStarted else {
      favoriteGate.resume(
        .failure(APIError(code: "server_error", message: "unsafe", retryable: true)))
      await update.value
      return
    }

    favoriteGate.resume(
      .failure(APIError(code: "server_error", message: "unsafe", retryable: true)))
    await update.value
    #expect(model.items == [original])
    #expect(model.error?.message == "Could not update favorite.")

    reloadGate.resume(
      .success(
        page([creatorCard(id, name: "Target", favorite: true)], cursor: "latest-cursor")))
    #expect(await eventually { !model.isLoadingFirstPage })

    #expect(model.items == [original])
    #expect(model.query == "failure query")
    #expect(model.nextCursor == "latest-cursor")
    #expect(model.error?.message == "Could not update favorite.")
    #expect(await api.favoriteCallCount == 1)
  }

  @MainActor
  @Test func queuedOnlyCollectionReloadSurvivesImmediateFavorite() async {
    let favoriteGate = CompletionGate<ProfileCard>()
    let reloadGate = CompletionGate<ProfileCardPage>()
    let id = UUID(uuidString: "00000000-0000-0000-0000-000000000423")!
    let original = creatorCard(id, name: "Target", favorite: false)
    let canonical = creatorCard(id, name: "Canonical Target", favorite: true)
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([original], cursor: "old-cursor")),
        .gated(reloadGate),
      ],
      favoriteOutcomes: [.gated(favoriteGate)])
    let model = LibraryModel(api: api, clock: ManualClock())
    await model.loadFirstPage()

    model.setOnlyCollection(true)
    let update = Task { await model.toggleFavorite(id: id) }
    await favoriteGate.waitUntilEntered()
    let reloadStarted = await eventually { await api.listCallCount == 2 }
    #expect(reloadStarted)
    guard reloadStarted else {
      favoriteGate.resume(.success(canonical))
      await update.value
      return
    }

    favoriteGate.resume(.success(canonical))
    await update.value
    #expect(model.items == [canonical])
    reloadGate.resume(.success(page([original], cursor: "filtered-cursor")))
    #expect(await eventually { !model.isLoadingFirstPage })

    #expect(model.items == [canonical])
    #expect(model.onlyCollection)
    #expect(model.nextCursor == "filtered-cursor")
    #expect(
      await api.listCalls[1]
        == ListCall(type: .creator, query: "", onlyCollection: true, cursor: nil, limit: 20))
  }

  @MainActor
  @Test func selectedSuccessfulAnalysisRefreshesOnceAndHighlightsForExactlyTwoSeconds() async {
    let clock = ManualClock()
    let firstAffectedID = UUID(uuidString: "00000000-0000-0000-0000-000000000501")!
    let lastAffectedID = UUID(uuidString: "00000000-0000-0000-0000-000000000503")!
    let unrelatedID = UUID(uuidString: "00000000-0000-0000-0000-000000000502")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([creatorCard(unrelatedID, name: "Before")], cursor: "before")),
        .page(
          page(
            [
              creatorCard(firstAffectedID, name: "First"),
              creatorCard(lastAffectedID, name: "Last"),
            ], cursor: nil)),
      ])
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()

    let ignored = JobChangeBatch(
      changes: [
        .analysis(analysisJob(type: .creator, status: .running, profileID: firstAffectedID)),
        .analysis(analysisJob(type: .creator, status: .failed, profileID: firstAffectedID)),
        .analysis(analysisJob(type: .creator, status: .succeeded, profileID: unrelatedID)),
        .match(matchJob(status: .succeeded)),
      ],
      affectedProfileIDs: [firstAffectedID], affectedMatchTaskIDs: [], affectedGameIDs: [],
      hasActiveJobs: false)
    await model.consume(jobBatch: ignored)
    #expect(await api.listCallCount == 1)

    let batch = JobChangeBatch(
      changes: [
        .analysis(analysisJob(type: .creator, status: .succeeded, profileID: firstAffectedID)),
        .analysis(analysisJob(type: .creator, status: .succeeded, profileID: lastAffectedID)),
      ],
      affectedProfileIDs: [firstAffectedID, lastAffectedID], affectedMatchTaskIDs: [],
      affectedGameIDs: [],
      hasActiveJobs: false)
    await model.consume(jobBatch: batch)

    #expect(await api.listCallCount == 2)
    #expect(model.items.map(\.id) == [firstAffectedID, lastAffectedID])
    #expect(model.highlightedProfileID == lastAffectedID)
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .milliseconds(1_999))
    await Task.yield()
    #expect(model.highlightedProfileID == lastAffectedID)
    await clock.advance(by: .milliseconds(1))
    #expect(await eventually { model.highlightedProfileID == nil })
  }

  @MainActor
  @Test func newerAnalysisHighlightOwnsItsOwnTwoSecondToken() async {
    let clock = ManualClock()
    let firstID = UUID(uuidString: "00000000-0000-0000-0000-000000000511")!
    let secondID = UUID(uuidString: "00000000-0000-0000-0000-000000000512")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([], cursor: nil)),
        .page(page([creatorCard(firstID, name: "First")], cursor: nil)),
        .page(page([creatorCard(secondID, name: "Second")], cursor: nil)),
      ])
    let model = LibraryModel(api: api, clock: clock)
    await model.loadFirstPage()

    await model.consume(jobBatch: successfulAnalysisBatch(profileID: firstID))
    #expect(model.highlightedProfileID == firstID)
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .seconds(1))

    await model.consume(jobBatch: successfulAnalysisBatch(profileID: secondID))
    #expect(model.highlightedProfileID == secondID)
    #expect(await eventually { await clock.pendingSleepCount == 1 })
    await clock.advance(by: .seconds(1))
    await Task.yield()
    #expect(model.highlightedProfileID == secondID)
    await clock.advance(by: .seconds(1))
    #expect(await eventually { model.highlightedProfileID == nil })
  }

  @MainActor
  @Test func inactiveSuccessfulAnalysisMarksDirtyAndRefreshesOnceWhenSelected() async {
    let gameID = UUID(uuidString: "00000000-0000-0000-0000-000000000601")!
    let api = LibraryAPI(
      listOutcomes: [
        .page(page([creatorCard(UUID(), name: "Creator")], cursor: nil)),
        .page(page([gameCard(gameID, name: "Game")], cursor: nil)),
      ])
    let model = LibraryModel(api: api, clock: ManualClock())
    await model.loadFirstPage()
    let batch = JobChangeBatch(
      changes: [.analysis(analysisJob(type: .game, status: .succeeded, profileID: gameID))],
      affectedProfileIDs: [gameID], affectedMatchTaskIDs: [], affectedGameIDs: [],
      hasActiveJobs: false)

    await model.consume(jobBatch: batch)
    #expect(model.selectedType == .creator)
    #expect(await api.listCallCount == 1)

    model.selectType(.game)
    #expect(await eventually { await api.listCallCount == 2 })
    #expect(await eventually { model.items.map(\.id) == [gameID] })
    model.selectType(.creator)
    model.selectType(.game)
    await Task.yield()
    #expect(await api.listCallCount == 2)
  }
}

enum FavoriteBadCompletion: Sendable {
  case failure
  case mismatched
}

private struct ListCall: Sendable, Equatable {
  let type: ProfileType
  let query: String
  let onlyCollection: Bool
  let cursor: String?
  let limit: Int
}

private struct FavoriteCall: Sendable, Equatable {
  let type: ProfileType
  let id: UUID
  let favorite: Bool
}

private enum GateResult<Value: Sendable>: Sendable {
  case success(Value)
  case failure(APIError)
}

private final class CompletionGate<Value: Sendable>: @unchecked Sendable {
  private let lock = NSLock()
  private var continuation: CheckedContinuation<GateResult<Value>, Never>?
  private var entered = false

  func wait() async -> GateResult<Value> {
    await withCheckedContinuation { continuation in
      lock.withLock {
        entered = true
        self.continuation = continuation
      }
    }
  }

  func waitUntilEntered() async {
    while !lock.withLock({ entered }) { await Task.yield() }
  }

  func resume(_ result: GateResult<Value>) {
    let pending = lock.withLock {
      let pending = continuation
      continuation = nil
      return pending
    }
    pending?.resume(returning: result)
  }
}

private enum ListOutcome: Sendable {
  case page(ProfileCardPage)
  case failure(APIError)
  case gated(CompletionGate<ProfileCardPage>)
}

private enum FavoriteOutcome: Sendable {
  case card(ProfileCard)
  case failure(APIError)
  case gated(CompletionGate<ProfileCard>)
}

private actor LibraryAPI: APIService {
  private var listOutcomes: [ListOutcome]
  private var favoriteOutcomes: [FavoriteOutcome]
  private(set) var listCalls: [ListCall] = []
  private(set) var favoriteCalls: [FavoriteCall] = []
  private(set) var requestedPages: [Int] = []

  func listCreatorPage(query: String, onlyCollection: Bool, page: Int) async throws -> ProfileCardPage {
    requestedPages.append(page)
    var result = try await listProfiles(type: .creator, query: query, onlyCollection: onlyCollection,
      cursor: page == 1 ? nil : String(page), limit: 20)
    if result.totalCount == nil {
      result.page = page
      result.totalPages = result.nextCursor == nil ? page : page + 1
    }
    return result
  }

  init(listOutcomes: [ListOutcome], favoriteOutcomes: [FavoriteOutcome] = []) {
    self.listOutcomes = listOutcomes
    self.favoriteOutcomes = favoriteOutcomes
  }

  var listCallCount: Int { listCalls.count }
  var favoriteCallCount: Int { favoriteCalls.count }

  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    try Task.checkCancellation()
    listCalls.append(
      ListCall(
        type: type, query: query, onlyCollection: onlyCollection, cursor: cursor, limit: limit))
    let outcome = listOutcomes.removeFirst()
    switch outcome {
    case .page(let value): return value
    case .failure(let error): throw error
    case .gated(let gate):
      switch await gate.wait() {
      case .success(let value): return value
      case .failure(let error): throw error
      }
    }
  }

  func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws -> ProfileCard {
    favoriteCalls.append(FavoriteCall(type: type, id: id, favorite: favorite))
    let outcome = favoriteOutcomes.removeFirst()
    switch outcome {
    case .card(let value): return value
    case .failure(let error): throw error
    case .gated(let gate):
      switch await gate.wait() {
      case .success(let value): return value
      case .failure(let error): throw error
      }
    }
  }

  func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage {
    fatalError("unused")
  }
  func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  { fatalError("unused") }
  func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    fatalError("unused")
  }
  func profile(type: ProfileType, id: UUID) async throws -> Profile { fatalError("unused") }
  func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  { fatalError("unused") }
  func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  func listMatches(cursor: String?) async throws -> MatchTaskPage { fatalError("unused") }
  func match(id: UUID) async throws -> MatchResult { fatalError("unused") }
  func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  func listCampaigns(cursor: String?) async throws -> CampaignPage { fatalError("unused") }
  func campaign(id: UUID) async throws -> OutreachCampaign { fatalError("unused") }
  func listTemplates() async throws -> [OutreachTemplate] { fatalError("unused") }
  func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  func duplicateTemplate(id: UUID) async throws -> OutreachTemplate { fatalError("unused") }
  func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate { fatalError("unused") }
  func deleteTemplate(id: UUID) async throws { fatalError("unused") }
  func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    fatalError("unused")
  }
  func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    fatalError("unused")
  }
  func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws -> SendBatch
  {
    fatalError("unused")
  }
  func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
  func smtpSettings() async throws -> SMTPSettingsStatus { fatalError("unused") }
  func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    fatalError("unused")
  }
  func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws -> ConnectionTestResult {
    fatalError("unused")
  }
  func sendSMTPTest(to email: String) async throws -> ConnectionTestResult { fatalError("unused") }
  func sharedSettings() async throws -> SharedSettings { fatalError("unused") }
  func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    fatalError("unused")
  }
  func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    fatalError("unused")
  }
  func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  { fatalError("unused") }
  func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult {
    fatalError("unused")
  }
}

@MainActor
private func eventually(_ predicate: @MainActor () async -> Bool) async -> Bool {
  for _ in 0..<300 {
    if await predicate() { return true }
    await Task.yield()
  }
  return await predicate()
}

private func page(_ items: [ProfileCard], cursor: String?) -> ProfileCardPage {
  ProfileCardPage(items: items, nextCursor: cursor)
}

private func creatorCard(
  _ id: UUID, name: String, favorite: Bool = false, contacts: [CreatorContact]? = nil
) -> ProfileCard {
  .creator(
    CreatorProfileCard(
      id: id, name: name, youtubeChannelID: "channel-\(id)",
      canonicalURL: "https://youtube.example/\(id)", favorite: favorite,
      currentFacts: [:], brief: [:], sourceStatus: [:], lastAnalyzedAt: nil,
      nextAnalysisAt: nil, contact: contacts?.first, contacts: contacts))
}

private func gameCard(
  _ id: UUID, name: String, favorite: Bool = false
) -> ProfileCard {
  .game(
    GameProfileCard(
      id: id, name: name, steamAppID: "app-\(id)",
      canonicalURL: "https://store.example/\(id)", favorite: favorite,
      currentFacts: [:], brief: [:], sourceStatus: [:], lastAnalyzedAt: nil,
      nextAnalysisAt: nil))
}

private func analysisJob(
  type: ProfileType, status: JobStatus, profileID: UUID?
) -> AnalysisJob {
  AnalysisJob(
    id: UUID(), profileType: type, canonicalTargetID: "target",
    canonicalURL: "https://example.test",
    mode: .create, status: status, stage: nil, completedUnits: 1, totalUnits: 1,
    retryable: false, correlationID: nil, profileID: profileID, createdAt: .distantPast,
    updatedAt: .distantPast, startedAt: nil, completedAt: nil, failure: nil)
}

private func successfulAnalysisBatch(profileID: UUID) -> JobChangeBatch {
  JobChangeBatch(
    changes: [.analysis(analysisJob(type: .creator, status: .succeeded, profileID: profileID))],
    affectedProfileIDs: [profileID], affectedMatchTaskIDs: [], affectedGameIDs: [],
    hasActiveJobs: false)
}

private func matchJob(status: JobStatus) -> ChangedMatchJob {
  ChangedMatchJob(
    id: UUID(), gameID: UUID(), status: status, stage: .ranking, completedUnits: 1,
    totalUnits: 1, resultCount: 0, retryable: false, failure: nil, correlationID: nil,
    supersedesID: nil, createdAt: .distantPast, updatedAt: .distantPast, startedAt: nil,
    completedAt: nil)
}
