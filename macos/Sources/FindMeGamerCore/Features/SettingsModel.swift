import Foundation
import Observation

@MainActor
public protocol AppearancePreferenceStoring: AnyObject {
  func string(forKey key: String) -> String?
  func set(_ value: String, forKey key: String)
}

@MainActor
public final class UserDefaultsAppearancePreferenceStore: AppearancePreferenceStoring {
  private let defaults: UserDefaults

  public init(defaults: UserDefaults = .standard) {
    self.defaults = defaults
  }

  public func string(forKey key: String) -> String? {
    defaults.string(forKey: key)
  }

  public func set(_ value: String, forKey key: String) {
    defaults.set(value, forKey: key)
  }
}

public struct ProfileAnalysisActivity: Sendable, Equatable {
  public let latestAnalysis: Date?
  public let nextReanalysis: Date?

  public init(latestAnalysis: Date?, nextReanalysis: Date?) {
    self.latestAnalysis = latestAnalysis
    self.nextReanalysis = nextReanalysis
  }

  public static let unavailable = ProfileAnalysisActivity(
    latestAnalysis: nil, nextReanalysis: nil)
}

@MainActor
@Observable
public final class SettingsModel {
  public static let appearanceModeKey = "appearance-mode"
  public static let fontSizeKey = "font-size"

  public let connectionServices: [ConnectionService] = [.steam, .youtube, .deepSeek]
  public let workspaceStatus: String
  public let apiBaseURL: String
  public let appVersion: String

  public private(set) var appearanceMode: AppearanceMode
  public private(set) var fontSize: FontSizePreference

  public private(set) var smtpStatus: SMTPSettingsStatus?
  public private(set) var smtpHost = ""
  public private(set) var smtpPort = 587
  public private(set) var smtpEncryption: SMTPEncryption? = .startTLS
  public private(set) var smtpUsername = ""
  public private(set) var smtpPassword = ""
  public private(set) var smtpFromName = ""
  public private(set) var smtpReplyTo = ""
  public private(set) var smtpEmailsPerMinute = 30
  public private(set) var smtpTestRecipient = ""
  public private(set) var isLoadingSMTP = false
  public private(set) var isSavingSMTP = false
  public private(set) var isTestingSMTP = false
  public private(set) var isSendingSMTPTest = false
  public private(set) var smtpLoadError: String?
  public private(set) var smtpActionError: String?

  public private(set) var sharedSettings: SharedSettings?
  public private(set) var gameIntervalDays = 30
  public private(set) var creatorIntervalDays = 14
  public private(set) var isLoadingReanalysis = false
  public private(set) var isSavingReanalysis = false
  public private(set) var reanalysisLoadError: String?
  public private(set) var reanalysisActionError: String?

  public private(set) var gameActivity = ProfileAnalysisActivity.unavailable
  public private(set) var creatorActivity = ProfileAnalysisActivity.unavailable
  public private(set) var isLoadingActivity = false

  public private(set) var isDisconnecting = false

  public var hasDisableScheduleControl: Bool { false }

  public var smtpIsDirty: Bool {
    guard let savedSMTPDraft else { return true }
    return currentSMTPDraft != savedSMTPDraft
  }

  public var canSaveSMTP: Bool {
    smtpStatus != nil && smtpDraftIsValid && smtpIsDirty && !smtpActionInFlight
  }

  public var canTestSMTP: Bool {
    smtpStatus?.configured == true && !smtpIsDirty && !smtpActionInFlight
  }

  public var canSendSMTPTest: Bool {
    canTestSMTP
      && Self.isBasicEmail(smtpTestRecipient.trimmingCharacters(in: .whitespacesAndNewlines))
  }

  public var canSaveReanalysis: Bool {
    sharedSettings != nil && (1...90).contains(gameIntervalDays)
      && (1...30).contains(creatorIntervalDays) && reanalysisIsDirty && !isSavingReanalysis
  }

  @ObservationIgnored private let api: any APIService
  @ObservationIgnored private let appearanceStore: any AppearancePreferenceStoring
  @ObservationIgnored private let disconnect: @MainActor @Sendable () async -> Void

  @ObservationIgnored private var savedSMTPDraft: SMTPSettingsDraft?
  @ObservationIgnored private var smtpHasUserEdits = false
  @ObservationIgnored private var smtpDraftRevision: UInt64 = 0
  @ObservationIgnored private var smtpStatusRevision: UInt64 = 0
  @ObservationIgnored private var smtpLoadGeneration: UInt64 = 0

  private var connectionStatuses: [ConnectionService: ConnectionStatus] = [:]
  private var connectionSecrets: [ConnectionService: String] = [:]
  private var connectionErrors: [ConnectionService: String] = [:]
  private var loadingConnections: Set<ConnectionService> = []
  private var connectionActions: Set<ConnectionService> = []
  @ObservationIgnored private var connectionStatusRevisions: [ConnectionService: UInt64] = [:]
  @ObservationIgnored private var connectionLoadGenerations: [ConnectionService: UInt64] = [:]

  @ObservationIgnored private var savedReanalysis: SharedSettings?
  @ObservationIgnored private var reanalysisHasUserEdits = false
  @ObservationIgnored private var reanalysisDraftRevision: UInt64 = 0
  @ObservationIgnored private var reanalysisStatusRevision: UInt64 = 0
  @ObservationIgnored private var reanalysisLoadGeneration: UInt64 = 0
  private var activityErrors: [ProfileType: String] = [:]
  @ObservationIgnored private var activityGeneration: UInt64 = 0

  public init(
    api: any APIService,
    appearanceStore: any AppearancePreferenceStoring = UserDefaultsAppearancePreferenceStore(),
    workspaceStatus: String = "Connected",
    apiBaseURL: String = "",
    appVersion: String = "",
    disconnect: @escaping @MainActor @Sendable () async -> Void = {}
  ) {
    self.api = api
    self.appearanceStore = appearanceStore
    self.workspaceStatus = workspaceStatus
    self.apiBaseURL = apiBaseURL
    self.appVersion = appVersion
    self.disconnect = disconnect
    appearanceMode = AppearanceMode.restoring(
      rawValue: appearanceStore.string(forKey: Self.appearanceModeKey))
    fontSize = FontSizePreference.restoring(
      rawValue: appearanceStore.string(forKey: Self.fontSizeKey))
  }

  public func setAppearanceMode(_ mode: AppearanceMode) {
    appearanceMode = mode
    appearanceStore.set(mode.rawValue, forKey: Self.appearanceModeKey)
  }

  public func setFontSize(_ size: FontSizePreference) {
    fontSize = size
    appearanceStore.set(size.rawValue, forKey: Self.fontSizeKey)
  }

  public func restoreAppearanceDefaults() {
    setAppearanceMode(.system)
    setFontSize(.default)
  }

  public func loadSMTPSettings() async {
    smtpLoadGeneration &+= 1
    let generation = smtpLoadGeneration
    let draftRevision = smtpDraftRevision
    let hadUnsavedDraft = smtpHasUserEdits && smtpIsDirty
    let statusRevision = smtpStatusRevision
    isLoadingSMTP = true
    smtpLoadError = nil
    defer {
      if smtpLoadGeneration == generation { isLoadingSMTP = false }
    }

    do {
      let status = try await api.smtpSettings()
      guard smtpLoadGeneration == generation, smtpStatusRevision == statusRevision
      else { return }
      let shouldAdoptDraft = !hadUnsavedDraft && smtpDraftRevision == draftRevision
      adoptSMTPStatus(status, updateDraft: shouldAdoptDraft)
    } catch {
      guard smtpLoadGeneration == generation, smtpStatusRevision == statusRevision
      else { return }
      smtpLoadError = Self.safeMessage(error, fallback: "Could not load Email Settings.")
    }
  }

  public func updateSMTPDraft(
    host: String,
    port: Int,
    encryption: SMTPEncryption?,
    username: String,
    password: String,
    fromName: String,
    replyTo: String,
    emailsPerMinute: Int
  ) {
    guard !smtpActionInFlight else { return }
    smtpHost = host
    smtpPort = port
    smtpEncryption = encryption
    smtpUsername = username
    smtpPassword = password
    smtpFromName = fromName
    smtpReplyTo = replyTo
    smtpEmailsPerMinute = emailsPerMinute
    smtpHasUserEdits = true
    smtpDraftRevision &+= 1
    smtpActionError = nil
  }

  public func updateSMTPPassword(_ password: String) {
    guard !smtpActionInFlight, smtpPassword != password else { return }
    smtpPassword = password
    smtpHasUserEdits = true
    smtpDraftRevision &+= 1
    smtpActionError = nil
  }

  public func updateSMTPTestRecipient(_ recipient: String) {
    guard !isSendingSMTPTest else { return }
    smtpTestRecipient = recipient
    smtpActionError = nil
  }

  public func saveSMTPSettings() async {
    guard canSaveSMTP else { return }
    let draft = currentSMTPDraft
    let sensitive = smtpPassword
    isSavingSMTP = true
    smtpActionError = nil
    defer { isSavingSMTP = false }

    do {
      let status = try await api.saveSMTPSettings(draft)
      smtpStatusRevision &+= 1
      adoptSMTPStatus(status, updateDraft: true)
    } catch {
      smtpActionError = Self.safeMessage(
        error, fallback: "Could not save Email Settings.", sensitive: sensitive)
    }
  }

  public func testSMTPConnection() async {
    guard smtpStatus?.configured == true, !smtpIsDirty else {
      smtpActionError = "Save Email Settings before testing the connection."
      return
    }
    guard !smtpActionInFlight else { return }
    isTestingSMTP = true
    smtpActionError = nil
    defer { isTestingSMTP = false }

    do {
      let result = try await api.testSMTPConnection(nil)
      smtpStatusRevision &+= 1
      applySMTPTestResult(result)
    } catch {
      smtpActionError = Self.safeMessage(error, fallback: "Could not test the SMTP connection.")
    }
  }

  public func sendSMTPTest() async {
    guard canSendSMTPTest else { return }
    let recipient = smtpTestRecipient.trimmingCharacters(in: .whitespacesAndNewlines)
    isSendingSMTPTest = true
    smtpActionError = nil
    defer { isSendingSMTPTest = false }

    do {
      let result = try await api.sendSMTPTest(to: recipient)
      smtpStatusRevision &+= 1
      applySMTPTestResult(result)
    } catch {
      smtpActionError = Self.safeMessage(error, fallback: "Could not send the test email.")
    }
  }

  public func connectionStatus(for service: ConnectionService) -> ConnectionStatus? {
    connectionStatuses[service]
  }

  public func connectionSecret(for service: ConnectionService) -> String {
    connectionSecrets[service] ?? ""
  }

  public func connectionError(for service: ConnectionService) -> String? {
    connectionErrors[service]
  }

  public func isLoadingConnection(_ service: ConnectionService) -> Bool {
    loadingConnections.contains(service)
  }

  public func isConnectionActionInFlight(_ service: ConnectionService) -> Bool {
    connectionActions.contains(service)
  }

  public func canTestConnection(_ service: ConnectionService) -> Bool {
    connectionServices.contains(service) && connectionStatuses[service]?.configured == true
      && connectionSecrets[service, default: ""].isEmpty
      && !connectionActions.contains(service)
  }

  public func updateConnectionSecret(_ secret: String, for service: ConnectionService) {
    guard connectionServices.contains(service), !connectionActions.contains(service) else { return }
    connectionSecrets[service] = secret
    connectionErrors[service] = nil
  }

  public func loadConnections() async {
    for service in connectionServices {
      await loadConnection(service)
    }
  }

  public func replaceConnection(_ service: ConnectionService) async {
    guard connectionServices.contains(service), !connectionActions.contains(service) else { return }
    let secret = connectionSecret(for: service)
    guard !secret.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      connectionErrors[service] = "Enter a replacement credential."
      return
    }
    connectionActions.insert(service)
    connectionErrors[service] = nil
    defer { connectionActions.remove(service) }

    do {
      let status = try await api.replaceConnection(service, secret: secret)
      guard status.service == service else {
        connectionErrors[service] = "Could not replace the \(service.displayName) credential."
        return
      }
      connectionStatusRevisions[service, default: 0] &+= 1
      connectionStatuses[service] = status
      connectionSecrets[service] = ""
    } catch {
      connectionErrors[service] = Self.safeMessage(
        error, fallback: "Could not replace the \(service.displayName) credential.",
        sensitive: secret)
    }
  }

  public func testConnection(_ service: ConnectionService) async {
    guard connectionServices.contains(service) else { return }
    guard !connectionActions.contains(service) else { return }
    guard connectionStatuses[service]?.configured == true else {
      connectionErrors[service] = "Configure \(service.displayName) before testing the connection."
      return
    }
    guard connectionSecrets[service, default: ""].isEmpty else {
      connectionErrors[service] =
        "Replace or clear the \(service.displayName) credential before testing the connection."
      return
    }
    connectionActions.insert(service)
    connectionErrors[service] = nil
    defer { connectionActions.remove(service) }

    do {
      let result = try await api.testConnection(service)
      connectionStatusRevisions[service, default: 0] &+= 1
      connectionStatuses[service] = ConnectionStatus(
        service: service, configured: true, lastTestStatus: result.status,
        lastTestedAt: result.testedAt)
    } catch {
      connectionErrors[service] = Self.safeMessage(
        error, fallback: "Could not test the \(service.displayName) connection.")
    }
  }

  public func updateReanalysis(gameIntervalDays: Int, creatorIntervalDays: Int) {
    guard !isSavingReanalysis else { return }
    self.gameIntervalDays = gameIntervalDays
    self.creatorIntervalDays = creatorIntervalDays
    reanalysisHasUserEdits = true
    reanalysisDraftRevision &+= 1
    reanalysisActionError = nil
  }

  public func loadReanalysis() async {
    reanalysisLoadGeneration &+= 1
    let generation = reanalysisLoadGeneration
    let draftRevision = reanalysisDraftRevision
    let hadUnsavedDraft = reanalysisHasUserEdits && reanalysisIsDirty
    let statusRevision = reanalysisStatusRevision
    isLoadingReanalysis = true
    reanalysisLoadError = nil
    defer {
      if reanalysisLoadGeneration == generation { isLoadingReanalysis = false }
    }

    do {
      let settings = try await api.sharedSettings()
      guard reanalysisLoadGeneration == generation,
        reanalysisStatusRevision == statusRevision
      else { return }
      sharedSettings = settings
      savedReanalysis = settings
      if !hadUnsavedDraft && reanalysisDraftRevision == draftRevision {
        gameIntervalDays = settings.gameIntervalDays
        creatorIntervalDays = settings.creatorIntervalDays
        reanalysisHasUserEdits = false
      }
    } catch {
      guard reanalysisLoadGeneration == generation,
        reanalysisStatusRevision == statusRevision
      else { return }
      reanalysisLoadError = Self.safeMessage(
        error, fallback: "Could not load Re-analysis Settings.")
    }
  }

  public func saveReanalysis() async {
    guard canSaveReanalysis else { return }
    let draft = ReanalysisDraft(
      gameIntervalDays: gameIntervalDays, creatorIntervalDays: creatorIntervalDays)
    isSavingReanalysis = true
    reanalysisActionError = nil
    defer { isSavingReanalysis = false }

    do {
      let settings = try await api.saveReanalysis(draft)
      reanalysisStatusRevision &+= 1
      sharedSettings = settings
      savedReanalysis = settings
      gameIntervalDays = settings.gameIntervalDays
      creatorIntervalDays = settings.creatorIntervalDays
      reanalysisHasUserEdits = false
    } catch {
      reanalysisActionError = Self.safeMessage(
        error, fallback: "Could not save Re-analysis Settings.")
    }
  }

  public func loadProfileActivity() async {
    activityGeneration &+= 1
    let generation = activityGeneration
    isLoadingActivity = true
    activityErrors = [:]
    defer {
      if activityGeneration == generation { isLoadingActivity = false }
    }

    await loadActivity(for: .game, generation: generation)
    await loadActivity(for: .creator, generation: generation)
  }

  public func activityError(for type: ProfileType) -> String? {
    activityErrors[type]
  }

  public func disconnectThisMac() async {
    guard !isDisconnecting else { return }
    isDisconnecting = true
    defer { isDisconnecting = false }
    await disconnect()
  }

  private var smtpActionInFlight: Bool {
    isSavingSMTP || isTestingSMTP || isSendingSMTPTest
  }

  private var smtpDraftIsValid: Bool {
    let passwordIsValid =
      smtpStatus?.configured == true
      || !smtpPassword.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    return !smtpHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && (1...65535).contains(smtpPort) && smtpEncryption != nil
      && Self.isBasicEmail(smtpUsername.trimmingCharacters(in: .whitespacesAndNewlines))
      && !smtpFromName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && Self.isBasicEmail(smtpReplyTo.trimmingCharacters(in: .whitespacesAndNewlines))
      && (1...60).contains(smtpEmailsPerMinute) && passwordIsValid
  }

  private var currentSMTPDraft: SMTPSettingsDraft {
    SMTPSettingsDraft(
      host: smtpHost, port: smtpPort, encryption: smtpEncryption, username: smtpUsername,
      password: smtpPassword.isEmpty ? nil : smtpPassword, fromName: smtpFromName,
      replyTo: smtpReplyTo, emailsPerMinute: smtpEmailsPerMinute)
  }

  private var reanalysisIsDirty: Bool {
    guard let savedReanalysis else { return true }
    return savedReanalysis.gameIntervalDays != gameIntervalDays
      || savedReanalysis.creatorIntervalDays != creatorIntervalDays
  }

  private func adoptSMTPStatus(_ status: SMTPSettingsStatus, updateDraft: Bool) {
    smtpStatus = status
    let visibleDraft = Self.smtpDraft(from: status)
    savedSMTPDraft = visibleDraft
    guard updateDraft else { return }
    smtpHost = visibleDraft.host
    smtpPort = visibleDraft.port ?? 587
    smtpEncryption = visibleDraft.encryption
    smtpUsername = visibleDraft.username
    smtpPassword = ""
    smtpFromName = visibleDraft.fromName
    smtpReplyTo = visibleDraft.replyTo
    smtpEmailsPerMinute = visibleDraft.emailsPerMinute ?? 30
    smtpHasUserEdits = false
    smtpDraftRevision &+= 1
  }

  private func applySMTPTestResult(_ result: ConnectionTestResult) {
    guard let status = smtpStatus else { return }
    smtpStatus = SMTPSettingsStatus(
      configured: status.configured, host: status.host, port: status.port,
      encryption: status.encryption, username: status.username, fromName: status.fromName,
      replyTo: status.replyTo, emailsPerMinute: status.emailsPerMinute,
      lastTestStatus: result.status, lastTestedAt: result.testedAt)
  }

  private func loadConnection(_ service: ConnectionService) async {
    connectionLoadGenerations[service, default: 0] &+= 1
    let generation = connectionLoadGenerations[service, default: 0]
    let statusRevision = connectionStatusRevisions[service, default: 0]
    loadingConnections.insert(service)
    connectionErrors[service] = nil
    defer {
      if connectionLoadGenerations[service] == generation {
        loadingConnections.remove(service)
      }
    }

    do {
      let status = try await api.connection(service)
      guard connectionLoadGenerations[service] == generation,
        connectionStatusRevisions[service, default: 0] == statusRevision
      else { return }
      guard status.service == service else {
        connectionErrors[service] = "Could not load the \(service.displayName) connection."
        return
      }
      connectionErrors[service] = nil
      connectionStatuses[service] = status
    } catch {
      guard connectionLoadGenerations[service] == generation,
        connectionStatusRevisions[service, default: 0] == statusRevision
      else { return }
      connectionErrors[service] = Self.safeMessage(
        error, fallback: "Could not load the \(service.displayName) connection.")
    }
  }

  private func loadActivity(for type: ProfileType, generation: UInt64) async {
    do {
      var cursor: String?
      var lastDates: [Date] = []
      var nextDates: [Date] = []
      repeat {
        let page = try await api.listProfiles(
          type: type, query: "", onlyCollection: false, cursor: cursor, limit: 100)
        for item in page.items {
          switch (type, item) {
          case (.game, .game(let profile)):
            if let date = profile.lastAnalyzedAt { lastDates.append(date) }
            if let date = profile.nextAnalysisAt { nextDates.append(date) }
          case (.creator, .creator(let profile)):
            if let date = profile.lastAnalyzedAt { lastDates.append(date) }
            if let date = profile.nextAnalysisAt { nextDates.append(date) }
          default:
            continue
          }
        }
        cursor = page.nextCursor
      } while cursor != nil

      guard activityGeneration == generation else { return }
      let activity = ProfileAnalysisActivity(
        latestAnalysis: lastDates.max(), nextReanalysis: nextDates.min())
      if type == .game {
        gameActivity = activity
      } else {
        creatorActivity = activity
      }
    } catch {
      guard activityGeneration == generation else { return }
      activityErrors[type] = "Profile activity is unavailable."
      if type == .game {
        gameActivity = .unavailable
      } else {
        creatorActivity = .unavailable
      }
    }
  }

  private static func smtpDraft(from status: SMTPSettingsStatus) -> SMTPSettingsDraft {
    SMTPSettingsDraft(
      host: status.host ?? "", port: status.port ?? 587,
      encryption: status.encryption ?? .startTLS, username: status.username ?? "",
      password: nil, fromName: status.fromName ?? "", replyTo: status.replyTo ?? "",
      emailsPerMinute: status.emailsPerMinute)
  }

  private static func isBasicEmail(_ value: String) -> Bool {
    let parts = value.split(separator: "@", omittingEmptySubsequences: false)
    return parts.count == 2 && !parts[0].isEmpty && parts[1].contains(".")
      && !parts[1].hasPrefix(".") && !parts[1].hasSuffix(".")
  }

  private static func safeMessage(
    _ error: Error,
    fallback: String,
    sensitive: String = ""
  ) -> String {
    guard let apiError = error as? APIError else { return fallback }
    let message = apiError.description
    guard sensitive.isEmpty || !message.contains(sensitive) else { return fallback }
    return message
  }
}
