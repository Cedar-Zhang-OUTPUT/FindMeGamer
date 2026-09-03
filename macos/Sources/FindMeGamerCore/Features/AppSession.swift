import Foundation
import Observation

@MainActor
@Observable
public final class AppSession {
  public enum State: Sendable, Equatable {
    case checking
    case needsKey
    case authenticated
    case offline
  }

  public typealias APIFactory = @MainActor @Sendable (URL, String) -> any APIService
  public typealias APIBaseURLProvider = @MainActor @Sendable () -> String?

  public private(set) var state: State = .checking
  public private(set) var message = "Checking workspace access…"
  public private(set) var workspaceSession: WorkspaceSession?
  public private(set) var service: (any APIService)?

  @ObservationIgnored private let apiFactory: APIFactory
  @ObservationIgnored private let keyStore: any WorkspaceKeyStore
  @ObservationIgnored private let apiBaseURLProvider: APIBaseURLProvider
  @ObservationIgnored private let connectivity: any ConnectivityMonitoring
  @ObservationIgnored private var restoreTask: Task<Void, Never>?
  @ObservationIgnored private var recoveryTask: Task<Void, Never>?
  @ObservationIgnored private var didRestore = false
  @ObservationIgnored private var isOnline = true
  @ObservationIgnored private var generation: UInt64 = 0

  public init(
    apiFactory: @escaping APIFactory,
    keyStore: any WorkspaceKeyStore,
    apiBaseURLProvider: @escaping APIBaseURLProvider,
    connectivity: any ConnectivityMonitoring
  ) {
    self.apiFactory = apiFactory
    self.keyStore = keyStore
    self.apiBaseURLProvider = apiBaseURLProvider
    self.connectivity = connectivity
    connectivity.start { [weak self] online in
      Task { @MainActor [weak self] in
        self?.connectivityChanged(online)
      }
    }
  }

  public static func live(bundle: Bundle = .main) -> AppSession {
    let configuredURL = bundle.object(forInfoDictionaryKey: "FMGAPIBaseURL") as? String
    return AppSession(
      apiFactory: { baseURL, key in
        OpenAPIService(baseURL: baseURL, keyProvider: { key })
      },
      keyStore: KeychainStore(),
      apiBaseURLProvider: { configuredURL },
      connectivity: ConnectivityMonitor())
  }

  public static func configured(bundle: Bundle = .main) -> AppSession {
    let demoFlag = bundle.object(forInfoDictionaryKey: "FMGDemoMode")
    let isDemo = (demoFlag as? Bool) ?? (demoFlag as? NSNumber)?.boolValue ?? false
    return isDemo ? demo() : live(bundle: bundle)
  }

  public static func demo() -> AppSession {
    let service = DemoAPIService()
    return AppSession(
      apiFactory: { _, _ in service },
      keyStore: DemoWorkspaceKeyStore(),
      apiBaseURLProvider: { "http://127.0.0.1" },
      connectivity: DemoConnectivityMonitor())
  }

  public func connect(key: String) async {
    guard !key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      state = .needsKey
      message = "Enter a Workspace Access Key to connect."
      return
    }
    guard let baseURL = resolvedBaseURL() else {
      showConfigurationFailure()
      return
    }

    let operationGeneration = beginOperation()
    recoveryTask?.cancel()
    recoveryTask = nil
    state = .checking
    message = "Checking workspace access…"
    workspaceSession = nil
    service = nil
    let candidateService = apiFactory(baseURL, key)
    do {
      let validatedSession = try await candidateService.validateSession()
      guard canCommit(operationGeneration) else { return }
      do {
        try await keyStore.save(key)
      } catch {
        guard canCommit(operationGeneration) else { return }
        state = .needsKey
        message = "The Workspace Access Key could not be saved on this Mac."
        return
      }
      guard canCommit(operationGeneration) else { return }
      service = candidateService
      workspaceSession = validatedSession
      state = isOnline ? .authenticated : .offline
      message = isOnline ? "Connected." : offlineMessage
      didRestore = true
    } catch let error as APIError where error.code == "workspace_key_invalid" {
      guard canCommit(operationGeneration) else { return }
      state = .needsKey
      message = safeInvalidKeyMessage(error.message, key: key)
    } catch {
      guard canCommit(operationGeneration) else { return }
      state = .offline
      message = offlineMessage
    }
  }

  public func restore() async {
    await restore(allowRepeat: false)
  }

  public func retryAccess(key: String) async {
    if key.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      await restore(allowRepeat: true)
    } else {
      await connect(key: key)
    }
  }

  private func restore(allowRepeat: Bool) async {
    if didRestore, !allowRepeat { return }
    if let restoreTask {
      await restoreTask.value
      return
    }

    let operationGeneration = beginOperation()
    let task = Task { @MainActor [weak self] in
      guard let self else { return }
      await self.performRestore(generation: operationGeneration)
    }
    restoreTask = task
    await task.value
    if generation == operationGeneration {
      restoreTask = nil
    }
  }

  public func disconnectThisMac() async {
    let operationGeneration = beginOperation()
    restoreTask?.cancel()
    restoreTask = nil
    recoveryTask?.cancel()
    recoveryTask = nil
    do {
      try await keyStore.delete()
    } catch {
      guard generation == operationGeneration else { return }
      state = .offline
      message = "The Workspace Access Key could not be removed from this Mac."
      return
    }
    guard generation == operationGeneration else { return }
    service = nil
    workspaceSession = nil
    didRestore = true
    state = .needsKey
    message = "Enter a Workspace Access Key to connect."
  }

  deinit {
    restoreTask?.cancel()
    recoveryTask?.cancel()
    connectivity.cancel()
  }

  private func performRestore(generation operationGeneration: UInt64) async {
    state = .checking
    message = "Checking workspace access…"
    guard let baseURL = resolvedBaseURL() else {
      showConfigurationFailure()
      return
    }

    let key: String?
    do {
      key = try await keyStore.read()
    } catch {
      guard canCommit(operationGeneration) else { return }
      service = nil
      workspaceSession = nil
      state = .offline
      message = "The Workspace Access Key could not be read from this Mac."
      return
    }
    guard canCommit(operationGeneration) else { return }
    guard let key else {
      service = nil
      workspaceSession = nil
      state = .needsKey
      message = "Enter a Workspace Access Key to connect."
      didRestore = true
      return
    }

    let restoredService = apiFactory(baseURL, key)
    service = restoredService
    do {
      let validatedSession = try await restoredService.validateSession()
      guard canCommit(operationGeneration) else { return }
      workspaceSession = validatedSession
      state = isOnline ? .authenticated : .offline
      message = isOnline ? "Connected." : offlineMessage
      didRestore = true
    } catch let error as APIError where error.code == "workspace_key_invalid" {
      guard canCommit(operationGeneration) else { return }
      await removeInvalidSavedKey(error: error, key: key, generation: operationGeneration)
      guard canCommit(operationGeneration) else { return }
      didRestore = true
    } catch {
      guard canCommit(operationGeneration) else { return }
      state = .offline
      message = offlineMessage
      didRestore = true
    }
  }

  private func connectivityChanged(_ online: Bool) {
    let wasOnline = isOnline
    isOnline = online
    if !online {
      guard service != nil else { return }
      state = .offline
      message = offlineMessage
      return
    }

    guard !wasOnline, state == .offline, service != nil, recoveryTask == nil else { return }
    let operationGeneration = beginOperation()
    recoveryTask = Task { @MainActor [weak self] in
      guard let self else { return }
      await self.recoverConnection(generation: operationGeneration)
      if self.generation == operationGeneration {
        self.recoveryTask = nil
      }
    }
  }

  private func recoverConnection(generation operationGeneration: UInt64) async {
    guard let service else { return }
    do {
      let validatedSession = try await service.validateSession()
      guard canCommit(operationGeneration) else { return }
      workspaceSession = validatedSession
      state = isOnline ? .authenticated : .offline
      message = isOnline ? "Connected." : offlineMessage
    } catch let error as APIError where error.code == "workspace_key_invalid" {
      guard canCommit(operationGeneration) else { return }
      let key = (try? await keyStore.read()) ?? ""
      guard canCommit(operationGeneration) else { return }
      await removeInvalidSavedKey(error: error, key: key, generation: operationGeneration)
    } catch {
      guard canCommit(operationGeneration) else { return }
      state = .offline
      message = offlineMessage
    }
  }

  private func removeInvalidSavedKey(
    error: APIError, key: String, generation operationGeneration: UInt64
  ) async {
    guard canCommit(operationGeneration) else { return }
    service = nil
    workspaceSession = nil
    state = .needsKey
    message = safeInvalidKeyMessage(error.message, key: key)
    do {
      try await keyStore.delete()
    } catch {
      guard canCommit(operationGeneration) else { return }
      message = "The invalid Workspace Access Key could not be removed from this Mac."
    }
  }

  private func beginOperation() -> UInt64 {
    generation &+= 1
    return generation
  }

  private func canCommit(_ operationGeneration: UInt64) -> Bool {
    generation == operationGeneration && !Task.isCancelled
  }

  private func resolvedBaseURL() -> URL? {
    guard let rawValue = apiBaseURLProvider(), !rawValue.isEmpty,
      let url = URL(string: rawValue),
      let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
      let host = url.host, !host.isEmpty
    else { return nil }
    return url
  }

  private func showConfigurationFailure() {
    service = nil
    workspaceSession = nil
    state = .offline
    message = "The app configuration does not contain a valid API address."
  }

  private func safeInvalidKeyMessage(_ candidate: String, key: String) -> String {
    guard !candidate.isEmpty, !candidate.contains(key) else {
      return "The Workspace Access Key is invalid."
    }
    return candidate
  }

  private var offlineMessage: String {
    "The workspace service is temporarily unavailable. Check your connection and try again."
  }
}
