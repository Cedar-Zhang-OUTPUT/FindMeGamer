import Foundation
import Observation

public struct ClientBatchRouting: Sendable, Equatable {
  public let refreshLibrary: Bool
  public let refreshMatch: Bool

  public static let analyzeOnly = ClientBatchRouting(
    refreshLibrary: false,
    refreshMatch: false)

  public init(refreshLibrary: Bool, refreshMatch: Bool) {
    self.refreshLibrary = refreshLibrary
    self.refreshMatch = refreshMatch
  }

  public init(batch: JobChangeBatch) {
    refreshLibrary = !batch.affectedProfileIDs.isEmpty
    refreshMatch = !batch.affectedMatchTaskIDs.isEmpty || !batch.affectedGameIDs.isEmpty
  }
}

@MainActor
@Observable
public final class ClientCoordinator {
  public let library: LibraryModel
  public let analyze: AnalyzeRequestModel
  public let match: MatchModel
  public let outreach: OutreachManagementModel
  public let composer: OutreachComposerModel
  public let settings: SettingsModel
  public let jobPoller: JobPoller

  public private(set) var presentedProfile: Profile?
  public private(set) var isLoadingProfile = false
  public private(set) var profileLoadError: String?

  public var isProfilePresentationActive: Bool {
    isLoadingProfile || presentedProfile != nil || profileLoadError != nil
  }

  @ObservationIgnored private let api: any APIService
  @ObservationIgnored private var isRunning = false
  @ObservationIgnored private var profileRequestGeneration: UInt64 = 0
  @ObservationIgnored private var requestedProfile: ProfileIdentity?
  @ObservationIgnored private var profileReanalysisKeys: [ProfileIdentity: String] = [:]
  @ObservationIgnored private var reanalyzingProfiles: Set<ProfileIdentity> = []

  public init(
    api: any APIService,
    apiBaseURL: String,
    appVersion: String,
    appearanceStore: any AppearancePreferenceStoring = UserDefaultsAppearancePreferenceStore(),
    workspaceIsOnline: Bool = true,
    idempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString },
    clock: any AppClock = ContinuousAppClock(),
    disconnect: @escaping @MainActor @Sendable () async -> Void = {}
  ) {
    self.api = api
    let poller = JobPoller(api: api, clock: clock)
    jobPoller = poller
    library = LibraryModel(api: api, clock: clock)
    analyze = AnalyzeRequestModel(
      api: api,
      idempotencyKey: idempotencyKey,
      onJobActivity: { await poller.refreshNow() })
    match = MatchModel(
      api: api,
      idempotencyKey: idempotencyKey,
      onJobActivity: { await poller.refreshNow() })
    outreach = OutreachManagementModel(
      api: api,
      clock: clock,
      idempotencyKey: idempotencyKey)
    composer = OutreachComposerModel(api: api, idempotencyKey: idempotencyKey)
    settings = SettingsModel(
      api: api,
      appearanceStore: appearanceStore,
      workspaceStatus: workspaceIsOnline ? "Connected" : "Offline",
      apiBaseURL: apiBaseURL,
      appVersion: appVersion,
      disconnect: disconnect)
  }

  public func run() async {
    guard !isRunning else { return }
    isRunning = true
    let poller = jobPoller
    await poller.start()

    await withTaskCancellationHandler {
      await withTaskGroup(of: Void.self) { group in
        group.addTask { await self.loadInitialData() }
        group.addTask { await self.consumeEvents() }
        await group.waitForAll()
      }
    } onCancel: {
      Task { await poller.stop() }
    }

    await poller.stop()
    isRunning = false
  }

  public func loadInitialData() async {
    async let libraryLoad: Void = library.loadFirstPage()
    async let smtpLoad: Void = settings.loadSMTPSettings()
    async let connectionLoad: Void = settings.loadConnections()
    async let reanalysisLoad: Void = settings.loadReanalysis()
    async let activityLoad: Void = settings.loadProfileActivity()
    _ = await (libraryLoad, smtpLoad, connectionLoad, reanalysisLoad, activityLoad)
  }

  public func consume(_ batch: JobChangeBatch) async {
    analyze.consume(jobBatch: batch)
    let routing = ClientBatchRouting(batch: batch)
    if routing.refreshLibrary {
      await library.consume(jobBatch: batch)
    }
    if routing.refreshMatch {
      await match.consume(jobBatch: batch)
    }
  }

  public func sceneBecameActive(visible: AppDestination) async {
    await jobPoller.refreshNow()
    await refreshVisibleWorkspace(visible)
  }

  public func workspaceConnectionChanged(isOnline: Bool, visible: AppDestination) async {
    settings.updateWorkspaceConnection(isOnline: isOnline)
    guard isOnline else { return }
    await jobPoller.refreshNow()
    await refreshVisibleWorkspace(visible)
  }

  public func openProfile(type: ProfileType, id: UUID) async {
    profileRequestGeneration &+= 1
    let generation = profileRequestGeneration
    requestedProfile = ProfileIdentity(type: type, id: id)
    presentedProfile = nil
    profileLoadError = nil
    isLoadingProfile = true

    do {
      let profile = try await api.profile(type: type, id: id)
      guard profileRequestGeneration == generation,
        requestedProfile == ProfileIdentity(type: type, id: id)
      else { return }
      guard Self.profile(profile, matches: type, id: id) else {
        profileLoadError = "Could not load Profile."
        isLoadingProfile = false
        return
      }
      presentedProfile = profile
      isLoadingProfile = false
    } catch {
      guard profileRequestGeneration == generation,
        requestedProfile == ProfileIdentity(type: type, id: id)
      else { return }
      profileLoadError = "Could not load Profile."
      isLoadingProfile = false
    }
  }

  public func retryProfileOpen() async {
    guard let requestedProfile else { return }
    await openProfile(type: requestedProfile.type, id: requestedProfile.id)
  }

  public func dismissProfile() {
    profileRequestGeneration &+= 1
    requestedProfile = nil
    presentedProfile = nil
    profileLoadError = nil
    isLoadingProfile = false
  }

  public func setProfileFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws
    -> ProfileCard
  {
    let card = try await api.setFavorite(type: type, id: id, favorite: favorite)
    guard Self.card(card, matches: type, id: id) else {
      throw APIError(
        code: "invalid_response",
        message: "The server returned a different profile.",
        retryable: false)
    }
    await refreshLibraryIfSelected(type)
    return card
  }

  public func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  {
    let profile = try await api.updateCreatorManual(id: id, email: email, notes: notes)
    guard profile.id == id else {
      throw APIError(
        code: "invalid_response",
        message: "The server returned a different profile.",
        retryable: false)
    }
    await refreshLibraryIfSelected(.creator)
    return profile
  }

  public func reanalyzeProfile(
    type: ProfileType,
    id: UUID,
    callerIdempotencyKey: String
  ) async throws {
    let identity = ProfileIdentity(type: type, id: id)
    guard reanalyzingProfiles.insert(identity).inserted else {
      throw APIError(
        code: "action_in_progress",
        message: "Re-analysis is already in progress.",
        retryable: true)
    }
    defer { reanalyzingProfiles.remove(identity) }

    guard let profile = presentedProfile,
      Self.profile(profile, matches: type, id: id),
      let canonicalURL = Self.canonicalURL(for: profile)
    else {
      throw APIError(
        code: "profile_unavailable",
        message: "The Profile is no longer available.",
        retryable: true)
    }

    let suppliedKey = UUID(uuidString: callerIdempotencyKey)?.uuidString ?? UUID().uuidString
    let key = profileReanalysisKeys[identity] ?? suppliedKey
    profileReanalysisKeys[identity] = key
    _ = try await api.createAnalysisJob(
      AnalysisRequest(url: canonicalURL, profileType: type, mode: .reanalyze),
      idempotencyKey: key)
    profileReanalysisKeys[identity] = nil
    await jobPoller.refreshNow()
  }

  public func sendBatchAccepted(_ batch: SendBatch) async {
    async let campaigns: Void = outreach.refreshCampaignsAfterAcceptedSend()
    if let matchID = batch.matchTaskID, match.selectedMatchID == matchID {
      async let result: Void = match.openResult(id: matchID)
      _ = await (campaigns, result)
    } else {
      await campaigns
    }
  }

  public func resendDelivery(id: UUID) async {
    let selectedMatchID = match.selectedMatchID
    await outreach.resendDelivery(id: id)
    guard let selectedMatchID, match.selectedMatchID == selectedMatchID else { return }
    await match.openResult(id: selectedMatchID)
  }

  private func consumeEvents() async {
    for await batch in jobPoller.events {
      if Task.isCancelled { return }
      await consume(batch)
    }
  }

  private func refreshVisibleWorkspace(_ destination: AppDestination) async {
    switch destination {
    case .library:
      await library.loadFirstPage()
    case .match:
      async let games: Void = match.loadGames()
      async let history: Void = match.loadHistory()
      if let selectedMatchID = match.selectedMatchID {
        async let result: Void = match.openResult(id: selectedMatchID)
        _ = await (games, history, result)
      } else {
        _ = await (games, history)
      }
    case .outreach:
      switch outreach.selectedTab {
      case .campaigns:
        await outreach.loadCampaigns()
      case .templates:
        await outreach.loadTemplates()
      case .emailSettings:
        await settings.loadSMTPSettings()
      }
    case .settings:
      async let connectionLoad: Void = settings.loadConnections()
      async let reanalysisLoad: Void = settings.loadReanalysis()
      async let activityLoad: Void = settings.loadProfileActivity()
      _ = await (connectionLoad, reanalysisLoad, activityLoad)
    }
  }

  private func refreshLibraryIfSelected(_ type: ProfileType) async {
    guard library.selectedType == type else { return }
    await library.loadFirstPage()
  }

  private static func profile(_ profile: Profile, matches type: ProfileType, id: UUID) -> Bool {
    switch (type, profile) {
    case (.game, .game(let value)): value.id == id
    case (.creator, .creator(let value)): value.id == id
    default: false
    }
  }

  private static func card(_ card: ProfileCard, matches type: ProfileType, id: UUID) -> Bool {
    switch (type, card) {
    case (.game, .game(let value)): value.id == id
    case (.creator, .creator(let value)): value.id == id
    default: false
    }
  }

  private static func canonicalURL(for profile: Profile) -> String? {
    switch profile {
    case .game(let value): value.canonicalURL
    case .creator(let value): value.canonicalURL
    }
  }
}

private struct ProfileIdentity: Hashable {
  let type: ProfileType
  let id: UUID
}
