import Foundation
import Observation
import Testing

@testable import FindMeGamerCore

private let smtpCanary = "CANARY_SMTP_CREDENTIAL_TASK15"
private let serviceCanary = "CANARY_SERVICE_CREDENTIAL_TASK15"

@Suite(.serialized)
struct SettingsModelTests {
  @MainActor
  @Test func connectionPresentationStatePublishesObservationChanges() async {
    let api = SettingsAPI(connectionLoadOutcomes: [
      .value(connection(.steam, configured: true)),
      .value(connection(.youtube)),
      .value(connection(.deepSeek)),
    ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())
    let probe = SettingsObservationProbe()

    withObservationTracking {
      _ = model.connectionStatus(for: .steam)
    } onChange: {
      probe.markChanged()
    }

    await model.loadConnections()

    #expect(probe.didChange)
  }

  @MainActor
  @Test func appearanceRestoresPersistsExactValuesAndSchedulesStayMandatory() async {
    let store = SettingsPreferenceStore(values: [
      "appearance-mode": AppearanceMode.light.rawValue,
      "font-size": FontSizePreference.large.rawValue,
    ])
    let api = SettingsAPI()
    let model = SettingsModel(api: api, appearanceStore: store)

    #expect(model.appearanceMode == .light)
    #expect(model.fontSize == .large)
    #expect(model.creatorIntervalDays == 14)
    #expect(model.gameIntervalDays == 30)
    #expect(!model.hasDisableScheduleControl)
    #expect(model.connectionServices == [.steam, .youtube, .deepSeek])

    model.setAppearanceMode(.dark)
    model.setFontSize(.extraLarge)
    #expect(store.value(forKey: "appearance-mode") == AppearanceMode.dark.rawValue)
    #expect(store.value(forKey: "font-size") == FontSizePreference.extraLarge.rawValue)

    model.restoreAppearanceDefaults()
    #expect(model.appearanceMode == .system)
    #expect(model.fontSize == .default)
    #expect(store.value(forKey: "appearance-mode") == AppearanceMode.system.rawValue)
    #expect(store.value(forKey: "font-size") == FontSizePreference.default.rawValue)

    model.updateReanalysis(gameIntervalDays: 0, creatorIntervalDays: 31)
    #expect(!model.canSaveReanalysis)
    model.updateReanalysis(gameIntervalDays: 91, creatorIntervalDays: 1)
    #expect(!model.canSaveReanalysis)
    #expect(await api.totalCallCount == 0)
  }

  @MainActor
  @Test func firstSMTPConfigurationRequiresAndClearsAnExactReplacementCredential() async {
    let unconfigured = smtpStatus(configured: false)
    let canonical = smtpStatus(
      configured: true, host: "smtp.internal", port: 465, encryption: .tls,
      username: "mailer@company.test", fromName: "Creator Team",
      replyTo: "reply@company.test", rate: 12)
    let api = SettingsAPI(
      smtpLoadOutcomes: [.value(unconfigured)], smtpSaveOutcomes: [.value(canonical)])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())

    await model.loadSMTPSettings()
    #expect(model.smtpStatus == unconfigured)
    #expect(model.smtpPassword.isEmpty)
    let statusLabels = Mirror(reflecting: unconfigured).children.compactMap(\.label)
    #expect(!statusLabels.contains("password"))
    #expect(!statusLabels.contains("secret"))

    model.updateSMTPDraft(
      host: "smtp.internal", port: 465, encryption: .tls,
      username: "mailer@company.test", password: "", fromName: "Creator Team",
      replyTo: "reply@company.test", emailsPerMinute: 12)
    #expect(!model.canSaveSMTP)
    model.updateSMTPPassword(smtpCanary)
    #expect(model.canSaveSMTP)

    await model.saveSMTPSettings()

    #expect(model.smtpStatus == canonical)
    #expect(model.smtpPassword.isEmpty)
    #expect(!model.smtpIsDirty)
    let saved = await api.smtpSaveCalls.first
    #expect(saved?.host == "smtp.internal")
    #expect(saved?.port == 465)
    #expect(saved?.encryption == .tls)
    #expect(saved?.username == "mailer@company.test")
    #expect(saved?.fromName == "Creator Team")
    #expect(saved?.replyTo == "reply@company.test")
    #expect(saved?.emailsPerMinute == 12)
    let exactCredentialForwarded = saved?.password == smtpCanary
    #expect(exactCredentialForwarded)
  }

  @MainActor
  @Test func configuredSMTPSaveRetainsFailureDraftAndSingleFlightsWithBlankPassword() async {
    let initial = smtpStatus(configured: true, host: "old.smtp", fromName: "Old Name")
    let canonical = smtpStatus(configured: true, host: "new.smtp", fromName: "New Name")
    let saveGate = SettingsGate<SMTPSettingsStatus>()
    let api = SettingsAPI(
      smtpLoadOutcomes: [.value(initial)],
      smtpSaveOutcomes: [
        .failure(
          APIError(
            code: "smtp_rejected", message: "Rejected \(smtpCanary)", retryable: true)),
        .gated(saveGate),
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())
    await model.loadSMTPSettings()

    model.updateSMTPDraft(
      host: "new.smtp", port: initial.port ?? 587, encryption: initial.encryption,
      username: initial.username ?? "", password: smtpCanary, fromName: "New Name",
      replyTo: initial.replyTo ?? "", emailsPerMinute: initial.emailsPerMinute)
    await model.saveSMTPSettings()
    #expect(model.smtpStatus == initial)
    #expect(model.smtpPassword == smtpCanary)
    #expect(model.smtpActionError == "Could not save Email Settings.")

    model.updateSMTPPassword("")
    let save = Task { await model.saveSMTPSettings() }
    #expect(await saveGate.waitUntilEntered())
    #expect(model.isSavingSMTP)
    await model.saveSMTPSettings()
    #expect(await api.smtpSaveCalls.count == 2)
    let preservesServerCredential = await api.smtpSaveCalls.last?.password == nil
    #expect(preservesServerCredential)
    saveGate.resume(.success(canonical))
    await save.value

    #expect(model.smtpStatus == canonical)
    #expect(model.smtpPassword.isEmpty)
    #expect(!model.isSavingSMTP)
  }

  @MainActor
  @Test func smtpReadTypingAndMutationFencesProtectSavedOnlyTestsAndOneTestEmail() async {
    let initial = smtpStatus(configured: true, host: "saved.smtp", testStatus: .notTested)
    let stale = smtpStatus(configured: true, host: "stale.smtp", testStatus: .failed)
    let loadGate = SettingsGate<SMTPSettingsStatus>()
    let mutationLoadGate = SettingsGate<SMTPSettingsStatus>()
    let sendGate = SettingsGate<ConnectionTestResult>()
    let connectionResult = testResult(.success, at: 100)
    let sendResult = testResult(.success, at: 110)
    let api = SettingsAPI(
      smtpLoadOutcomes: [.value(initial), .gated(loadGate), .gated(mutationLoadGate)],
      smtpTestOutcomes: [.value(connectionResult)], smtpSendOutcomes: [.gated(sendGate)])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())
    await model.loadSMTPSettings()

    let lateLoad = Task { await model.loadSMTPSettings() }
    #expect(await loadGate.waitUntilEntered())
    model.updateSMTPDraft(
      host: "typed.smtp", port: initial.port ?? 587, encryption: initial.encryption,
      username: initial.username ?? "", password: "", fromName: initial.fromName ?? "",
      replyTo: initial.replyTo ?? "", emailsPerMinute: initial.emailsPerMinute)
    await model.testSMTPConnection()
    #expect(await api.smtpTestCalls == 0)
    #expect(model.smtpActionError == "Save Email Settings before testing the connection.")
    loadGate.resume(.success(stale))
    await lateLoad.value
    #expect(model.smtpHost == "typed.smtp")

    model.updateSMTPDraft(
      host: stale.host ?? "", port: stale.port ?? 587, encryption: stale.encryption,
      username: stale.username ?? "", password: "", fromName: stale.fromName ?? "",
      replyTo: stale.replyTo ?? "", emailsPerMinute: stale.emailsPerMinute)
    let mutationRead = Task { await model.loadSMTPSettings() }
    #expect(await mutationLoadGate.waitUntilEntered())
    await model.testSMTPConnection()
    mutationLoadGate.resume(.success(stale))
    await mutationRead.value
    #expect(await api.smtpTestCalls == 1)
    #expect(model.smtpStatus?.lastTestStatus == .success)
    #expect(model.smtpStatus?.lastTestedAt == Date(timeIntervalSince1970: 100))

    model.updateSMTPTestRecipient("  coworker@company.test  ")
    let send = Task { await model.sendSMTPTest() }
    #expect(await sendGate.waitUntilEntered())
    await model.sendSMTPTest()
    #expect(await api.smtpSendCalls == ["coworker@company.test"])
    sendGate.resume(.success(sendResult))
    await send.value
    #expect(model.smtpStatus?.lastTestedAt == Date(timeIntervalSince1970: 110))
    #expect(!model.isSendingSMTPTest)
  }

  @MainActor
  @Test func smtpLoadsPublishCanonicalStateWithoutReplacingAuthoredDrafts() async {
    let firstGate = SettingsGate<SMTPSettingsStatus>()
    let firstCanonical = smtpStatus(configured: false, host: nil)
    let firstAPI = SettingsAPI(smtpLoadOutcomes: [.gated(firstGate)])
    let firstModel = SettingsModel(
      api: firstAPI, appearanceStore: SettingsPreferenceStore())

    let firstLoad = Task { await firstModel.loadSMTPSettings() }
    #expect(await firstGate.waitUntilEntered())
    firstModel.updateSMTPDraft(
      host: "authored.smtp", port: 465, encryption: .tls,
      username: "author@company.test", password: smtpCanary, fromName: "Authored Team",
      replyTo: "reply-authored@company.test", emailsPerMinute: 18)
    firstGate.resume(.success(firstCanonical))
    await firstLoad.value

    #expect(firstModel.smtpStatus == firstCanonical)
    #expect(firstModel.smtpHost == "authored.smtp")
    #expect(firstModel.smtpPort == 465)
    #expect(firstModel.smtpEncryption == .tls)
    #expect(firstModel.smtpUsername == "author@company.test")
    #expect(firstModel.smtpPassword == smtpCanary)
    #expect(firstModel.smtpFromName == "Authored Team")
    #expect(firstModel.smtpReplyTo == "reply-authored@company.test")
    #expect(firstModel.smtpEmailsPerMinute == 18)
    #expect(firstModel.canSaveSMTP)

    let oldCanonical = smtpStatus(configured: true, host: "old.smtp")
    let newerCanonical = smtpStatus(configured: true, host: "server-new.smtp")
    let refreshGate = SettingsGate<SMTPSettingsStatus>()
    let refreshAPI = SettingsAPI(
      smtpLoadOutcomes: [.value(oldCanonical), .gated(refreshGate)])
    let refreshModel = SettingsModel(
      api: refreshAPI, appearanceStore: SettingsPreferenceStore())
    await refreshModel.loadSMTPSettings()
    refreshModel.updateSMTPDraft(
      host: "authored-refresh.smtp", port: 2525, encryption: SMTPEncryption.none,
      username: "refresh@company.test", password: smtpCanary, fromName: "Refresh Team",
      replyTo: "reply-refresh@company.test", emailsPerMinute: 22)

    let refresh = Task { await refreshModel.loadSMTPSettings() }
    #expect(await refreshGate.waitUntilEntered())
    refreshGate.resume(.success(newerCanonical))
    await refresh.value

    #expect(refreshModel.smtpStatus == newerCanonical)
    #expect(refreshModel.smtpHost == "authored-refresh.smtp")
    #expect(refreshModel.smtpPort == 2525)
    #expect(refreshModel.smtpEncryption == SMTPEncryption.none)
    #expect(refreshModel.smtpUsername == "refresh@company.test")
    #expect(refreshModel.smtpPassword == smtpCanary)
    #expect(refreshModel.smtpFromName == "Refresh Team")
    #expect(refreshModel.smtpReplyTo == "reply-refresh@company.test")
    #expect(refreshModel.smtpEmailsPerMinute == 22)
    #expect(refreshModel.canSaveSMTP)

    let cleanOld = smtpStatus(configured: true, host: "clean-old.smtp")
    let cleanNew = smtpStatus(configured: true, host: "clean-new.smtp", port: 465)
    let cleanAPI = SettingsAPI(smtpLoadOutcomes: [.value(cleanOld), .value(cleanNew)])
    let cleanModel = SettingsModel(api: cleanAPI, appearanceStore: SettingsPreferenceStore())
    await cleanModel.loadSMTPSettings()
    cleanModel.updateSMTPDraft(
      host: "temporary.smtp", port: cleanOld.port ?? 587, encryption: cleanOld.encryption,
      username: cleanOld.username ?? "", password: "", fromName: cleanOld.fromName ?? "",
      replyTo: cleanOld.replyTo ?? "", emailsPerMinute: cleanOld.emailsPerMinute)
    cleanModel.updateSMTPDraft(
      host: cleanOld.host ?? "", port: cleanOld.port ?? 587, encryption: cleanOld.encryption,
      username: cleanOld.username ?? "", password: "", fromName: cleanOld.fromName ?? "",
      replyTo: cleanOld.replyTo ?? "", emailsPerMinute: cleanOld.emailsPerMinute)
    #expect(!cleanModel.smtpIsDirty)

    await cleanModel.loadSMTPSettings()

    #expect(cleanModel.smtpStatus == cleanNew)
    #expect(cleanModel.smtpHost == "clean-new.smtp")
    #expect(cleanModel.smtpPort == 465)
    #expect(!cleanModel.smtpIsDirty)
  }

  @MainActor
  @Test func smtpInitialLoadFailurePreservesAuthoredDraftAndRetryPublishesCanonicalState() async {
    let failureGate = SettingsGate<SMTPSettingsStatus>()
    let canonical = smtpStatus(configured: false, host: nil)
    let api = SettingsAPI(
      smtpLoadOutcomes: [
        .gated(failureGate), .value(canonical),
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())

    let firstLoad = Task { await model.loadSMTPSettings() }
    #expect(await failureGate.waitUntilEntered())
    model.updateSMTPDraft(
      host: "authored.smtp", port: 465, encryption: .tls,
      username: "author@company.test", password: smtpCanary, fromName: "Authored Team",
      replyTo: "reply-authored@company.test", emailsPerMinute: 18)
    failureGate.resume(
      .failure(
        APIError(
          code: "smtp_unavailable", message: "Email Settings are unavailable.", retryable: true)))
    await firstLoad.value

    #expect(model.smtpStatus == nil)
    #expect(model.smtpHost == "authored.smtp")
    #expect(model.smtpPort == 465)
    #expect(model.smtpEncryption == .tls)
    #expect(model.smtpUsername == "author@company.test")
    #expect(model.smtpPassword == smtpCanary)
    #expect(model.smtpFromName == "Authored Team")
    #expect(model.smtpReplyTo == "reply-authored@company.test")
    #expect(model.smtpEmailsPerMinute == 18)
    #expect(model.smtpLoadError == "Email Settings are unavailable.")
    #expect(!model.canSaveSMTP)

    await model.loadSMTPSettings()

    #expect(model.smtpStatus == canonical)
    #expect(model.smtpHost == "authored.smtp")
    #expect(model.smtpPort == 465)
    #expect(model.smtpEncryption == .tls)
    #expect(model.smtpUsername == "author@company.test")
    #expect(model.smtpPassword == smtpCanary)
    #expect(model.smtpFromName == "Authored Team")
    #expect(model.smtpReplyTo == "reply-authored@company.test")
    #expect(model.smtpEmailsPerMinute == 18)
    #expect(model.smtpLoadError == nil)
    #expect(model.canSaveSMTP)
    #expect(await api.smtpLoadCalls == 2)
  }

  @MainActor
  @Test func connectionsExposeThreeServicesAndReplaceTestWithoutLeakingInputs() async {
    let steamInitial = connection(.steam, configured: false, status: .notTested)
    let youtubeInitial = connection(.youtube, configured: true, status: .notTested)
    let deepInitial = connection(.deepSeek, configured: false, status: .notTested)
    let steamCanonical = connection(.steam, configured: true, status: .success, at: 200)
    let steamGate = SettingsGate<ConnectionStatus>()
    let api = SettingsAPI(
      connectionLoadOutcomes: [.value(steamInitial), .value(youtubeInitial), .value(deepInitial)],
      connectionReplaceOutcomes: [
        .failure(
          APIError(
            code: "replace_failed", message: "Rejected \(serviceCanary)", retryable: true)),
        .gated(steamGate), .value(connection(.youtube, configured: true, status: .success)),
      ],
      connectionTestOutcomes: [.value(testResult(.success, at: 210))])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())
    await model.loadConnections()

    #expect(await api.connectionLoadCalls == [.steam, .youtube, .deepSeek])
    #expect(model.connectionServices == [.steam, .youtube, .deepSeek])
    #expect(model.connectionStatus(for: .steam) == steamInitial)
    let reflectedLabels = Mirror(reflecting: steamInitial).children.compactMap(\.label)
    #expect(!reflectedLabels.contains("secret"))

    model.updateConnectionSecret(serviceCanary, for: .steam)
    await model.replaceConnection(.steam)
    #expect(model.connectionSecret(for: .steam) == serviceCanary)
    #expect(model.connectionError(for: .steam) == "Could not replace the Steam credential.")

    let replacing = Task { await model.replaceConnection(.steam) }
    #expect(await steamGate.waitUntilEntered())
    await model.replaceConnection(.steam)
    #expect(await api.connectionReplaceCalls.count == 2)
    steamGate.resume(.success(steamCanonical))
    await replacing.value
    #expect(model.connectionSecret(for: .steam).isEmpty)
    #expect(model.connectionStatus(for: .steam) == steamCanonical)

    model.updateConnectionSecret(serviceCanary, for: .deepSeek)
    await model.replaceConnection(.deepSeek)
    #expect(model.connectionStatus(for: .deepSeek) == deepInitial)
    #expect(model.connectionSecret(for: .deepSeek) == serviceCanary)
    #expect(model.connectionError(for: .deepSeek) == "Could not replace the DeepSeek credential.")

    await model.testConnection(.youtube)
    #expect(await api.connectionTestCalls == [.youtube])
    #expect(model.connectionStatus(for: .youtube)?.lastTestStatus == .success)
    #expect(model.connectionStatus(for: .youtube)?.lastTestedAt == Date(timeIntervalSince1970: 210))
    #expect(model.connectionStatus(for: .steam) == steamCanonical)

    let exactSteamSecret = await api.connectionReplaceCalls[0].secret == serviceCanary
    let exactDeepSeekTarget = await api.connectionReplaceCalls[2].service == .deepSeek
    #expect(exactSteamSecret)
    #expect(exactDeepSeekTarget)
  }

  @MainActor
  @Test func successfulConnectionMutationFencesAnOlderStatusRead() async {
    let initial = connection(.steam, configured: false, status: .notTested)
    let stale = connection(.steam, configured: false, status: .failed, at: 300)
    let canonical = connection(.steam, configured: true, status: .success, at: 310)
    let staleGate = SettingsGate<ConnectionStatus>()
    let api = SettingsAPI(
      connectionLoadOutcomes: [
        .value(initial), .value(connection(.youtube)), .value(connection(.deepSeek)),
        .gated(staleGate), .value(connection(.youtube)), .value(connection(.deepSeek)),
      ],
      connectionReplaceOutcomes: [.value(canonical)])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())
    await model.loadConnections()

    let read = Task { await model.loadConnections() }
    #expect(await staleGate.waitUntilEntered())
    model.updateConnectionSecret(serviceCanary, for: .steam)
    await model.replaceConnection(.steam)
    staleGate.resume(.success(stale))
    await read.value

    #expect(model.connectionStatus(for: .steam) == canonical)
    #expect(model.connectionSecret(for: .steam).isEmpty)
  }

  @MainActor
  @Test func connectionTestWaitsForKnownConfiguredStateAndACommittedCredential() async {
    let steamGate = SettingsGate<ConnectionStatus>()
    let configured = connection(.steam, configured: true)
    let api = SettingsAPI(
      connectionLoadOutcomes: [
        .gated(steamGate), .value(connection(.youtube)), .value(connection(.deepSeek)),
      ],
      connectionTestOutcomes: [
        .value(testResult(.success, at: 320)), .value(testResult(.success, at: 321)),
        .value(testResult(.success, at: 322)),
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())

    let load = Task { await model.loadConnections() }
    #expect(await steamGate.waitUntilEntered())
    #expect(!model.canTestConnection(.steam))
    await model.testConnection(.steam)
    #expect(await api.connectionTestCalls.isEmpty)
    #expect(model.connectionStatus(for: .steam) == nil)
    #expect(model.connectionError(for: .steam) == "Configure Steam before testing the connection.")

    steamGate.resume(.success(configured))
    await load.value
    #expect(model.connectionStatus(for: .steam) == configured)
    #expect(model.connectionError(for: .steam) == nil)
    #expect(model.canTestConnection(.steam))

    model.updateConnectionSecret(serviceCanary, for: .steam)
    #expect(!model.canTestConnection(.steam))
    await model.testConnection(.steam)
    #expect(await api.connectionTestCalls.isEmpty)
    #expect(
      model.connectionError(for: .steam)
        == "Replace or clear the Steam credential before testing the connection.")

    model.updateConnectionSecret("", for: .steam)
    #expect(model.canTestConnection(.steam))
    await model.testConnection(.steam)
    #expect(await api.connectionTestCalls == [.steam])
    #expect(model.connectionStatus(for: .steam)?.configured == true)
    #expect(model.connectionStatus(for: .steam)?.lastTestStatus == .success)
    #expect(model.connectionStatus(for: .steam)?.lastTestedAt == Date(timeIntervalSince1970: 320))
  }

  @MainActor
  @Test func reanalysisDraftBoundsFailureAndReadMutationFencesPreserveCanonicalTruth() async {
    let initial = SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
    let stale = SharedSettings(gameIntervalDays: 10, creatorIntervalDays: 5)
    let canonical = SharedSettings(gameIntervalDays: 45, creatorIntervalDays: 20)
    let readGate = SettingsGate<SharedSettings>()
    let saveGate = SettingsGate<SharedSettings>()
    let api = SettingsAPI(
      sharedLoadOutcomes: [.value(initial), .gated(readGate)],
      sharedSaveOutcomes: [
        .failure(APIError(code: "save_failed", message: "Could not update.", retryable: true)),
        .gated(saveGate),
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())
    await model.loadReanalysis()
    #expect(model.sharedSettings == initial)

    model.updateReanalysis(gameIntervalDays: 45, creatorIntervalDays: 20)
    #expect(model.canSaveReanalysis)
    await model.saveReanalysis()
    #expect(model.sharedSettings == initial)
    #expect(model.gameIntervalDays == 45)
    #expect(model.creatorIntervalDays == 20)

    let read = Task { await model.loadReanalysis() }
    #expect(await readGate.waitUntilEntered())
    let save = Task { await model.saveReanalysis() }
    #expect(await saveGate.waitUntilEntered())
    await model.saveReanalysis()
    #expect(await api.sharedSaveCalls.count == 2)
    saveGate.resume(.success(canonical))
    await save.value
    readGate.resume(.success(stale))
    await read.value

    #expect(model.sharedSettings == canonical)
    #expect(model.gameIntervalDays == 45)
    #expect(model.creatorIntervalDays == 20)
    #expect(
      await api.sharedSaveCalls.last
        == ReanalysisDraft(gameIntervalDays: 45, creatorIntervalDays: 20))
  }

  @MainActor
  @Test func reanalysisLoadsPublishCanonicalStateWithoutReplacingAuthoredDrafts() async {
    let firstGate = SettingsGate<SharedSettings>()
    let firstCanonical = SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
    let firstAPI = SettingsAPI(sharedLoadOutcomes: [.gated(firstGate)])
    let firstModel = SettingsModel(
      api: firstAPI, appearanceStore: SettingsPreferenceStore())

    let firstLoad = Task { await firstModel.loadReanalysis() }
    #expect(await firstGate.waitUntilEntered())
    firstModel.updateReanalysis(gameIntervalDays: 40, creatorIntervalDays: 18)
    firstGate.resume(.success(firstCanonical))
    await firstLoad.value

    #expect(firstModel.sharedSettings == firstCanonical)
    #expect(firstModel.gameIntervalDays == 40)
    #expect(firstModel.creatorIntervalDays == 18)
    #expect(firstModel.canSaveReanalysis)

    let oldCanonical = SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
    let newerCanonical = SharedSettings(gameIntervalDays: 35, creatorIntervalDays: 15)
    let refreshGate = SettingsGate<SharedSettings>()
    let refreshAPI = SettingsAPI(
      sharedLoadOutcomes: [.value(oldCanonical), .gated(refreshGate)])
    let refreshModel = SettingsModel(
      api: refreshAPI, appearanceStore: SettingsPreferenceStore())
    await refreshModel.loadReanalysis()
    refreshModel.updateReanalysis(gameIntervalDays: 45, creatorIntervalDays: 20)

    let refresh = Task { await refreshModel.loadReanalysis() }
    #expect(await refreshGate.waitUntilEntered())
    refreshGate.resume(.success(newerCanonical))
    await refresh.value

    #expect(refreshModel.sharedSettings == newerCanonical)
    #expect(refreshModel.gameIntervalDays == 45)
    #expect(refreshModel.creatorIntervalDays == 20)
    #expect(refreshModel.canSaveReanalysis)

    let cleanOld = SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
    let cleanNew = SharedSettings(gameIntervalDays: 35, creatorIntervalDays: 16)
    let cleanAPI = SettingsAPI(
      sharedLoadOutcomes: [.value(cleanOld), .value(cleanNew)])
    let cleanModel = SettingsModel(api: cleanAPI, appearanceStore: SettingsPreferenceStore())
    await cleanModel.loadReanalysis()
    cleanModel.updateReanalysis(gameIntervalDays: 31, creatorIntervalDays: 15)
    cleanModel.updateReanalysis(gameIntervalDays: 30, creatorIntervalDays: 14)
    #expect(!cleanModel.canSaveReanalysis)

    await cleanModel.loadReanalysis()

    #expect(cleanModel.sharedSettings == cleanNew)
    #expect(cleanModel.gameIntervalDays == 35)
    #expect(cleanModel.creatorIntervalDays == 16)
    #expect(!cleanModel.canSaveReanalysis)
  }

  @MainActor
  @Test func reanalysisSaveAndLoadFailuresKeepDistinctRecoveryPaths() async {
    let initial = SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
    let refreshed = SharedSettings(gameIntervalDays: 35, creatorIntervalDays: 15)
    let api = SettingsAPI(
      sharedLoadOutcomes: [
        .value(initial),
        .failure(
          APIError(
            code: "settings_unavailable", message: "Re-analysis Settings are unavailable.",
            retryable: true)),
        .value(refreshed),
      ],
      sharedSaveOutcomes: [
        .failure(APIError(code: "save_failed", message: "Could not update.", retryable: true))
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())

    await model.loadReanalysis()
    model.updateReanalysis(gameIntervalDays: 45, creatorIntervalDays: 20)
    await model.saveReanalysis()

    #expect(model.reanalysisActionError == "Could not update.")
    #expect(model.reanalysisLoadError == nil)
    #expect(model.sharedSettings == initial)
    #expect(model.gameIntervalDays == 45)
    #expect(model.creatorIntervalDays == 20)
    #expect(model.canSaveReanalysis)

    await model.loadReanalysis()

    #expect(model.reanalysisLoadError == "Re-analysis Settings are unavailable.")
    #expect(model.reanalysisActionError == "Could not update.")
    #expect(model.sharedSettings == initial)
    #expect(model.gameIntervalDays == 45)
    #expect(model.creatorIntervalDays == 20)
    #expect(model.canSaveReanalysis)

    await model.loadReanalysis()

    #expect(model.reanalysisLoadError == nil)
    #expect(model.reanalysisActionError == "Could not update.")
    #expect(model.sharedSettings == refreshed)
    #expect(model.gameIntervalDays == 45)
    #expect(model.creatorIntervalDays == 20)
    #expect(model.canSaveReanalysis)
  }

  @MainActor
  @Test func reanalysisInitialLoadFailurePreservesDraftAndRetryPublishesCanonicalState() async {
    let failureGate = SettingsGate<SharedSettings>()
    let canonical = SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14)
    let api = SettingsAPI(
      sharedLoadOutcomes: [
        .gated(failureGate), .value(canonical),
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())

    let firstLoad = Task { await model.loadReanalysis() }
    #expect(await failureGate.waitUntilEntered())
    model.updateReanalysis(gameIntervalDays: 40, creatorIntervalDays: 18)
    failureGate.resume(
      .failure(
        APIError(
          code: "settings_unavailable", message: "Re-analysis Settings are unavailable.",
          retryable: true)))
    await firstLoad.value

    #expect(model.sharedSettings == nil)
    #expect(model.gameIntervalDays == 40)
    #expect(model.creatorIntervalDays == 18)
    #expect(model.reanalysisLoadError == "Re-analysis Settings are unavailable.")
    #expect(model.reanalysisActionError == nil)
    #expect(!model.canSaveReanalysis)

    await model.loadReanalysis()

    #expect(model.sharedSettings == canonical)
    #expect(model.gameIntervalDays == 40)
    #expect(model.creatorIntervalDays == 18)
    #expect(model.reanalysisLoadError == nil)
    #expect(model.reanalysisActionError == nil)
    #expect(model.canSaveReanalysis)
    #expect(await api.sharedLoadCalls == 2)
  }

  @MainActor
  @Test func profileActivityDrainsOpaquePagesAndFailureDoesNotBlockSettingsSave() async {
    let gameA = gameCard(id: id(1), last: 10, next: 80)
    let gameB = gameCard(id: id(2), last: 30, next: 60)
    let creatorA = creatorCard(id: id(3), last: 20, next: 70)
    let creatorB = creatorCard(id: id(4), last: nil, next: 50)
    let canonical = SharedSettings(gameIntervalDays: 35, creatorIntervalDays: 15)
    let api = SettingsAPI(
      sharedLoadOutcomes: [.value(SharedSettings(gameIntervalDays: 30, creatorIntervalDays: 14))],
      sharedSaveOutcomes: [.value(canonical)],
      profileOutcomes: [
        .value(ProfileCardPage(items: [.game(gameA)], nextCursor: "game opaque +/")),
        .value(ProfileCardPage(items: [.game(gameB)], nextCursor: nil)),
        .value(ProfileCardPage(items: [.creator(creatorA), .creator(creatorB)], nextCursor: nil)),
        .failure(APIError(code: "activity_failed", message: "Unavailable.", retryable: true)),
        .value(ProfileCardPage(items: [], nextCursor: nil)),
      ])
    let model = SettingsModel(api: api, appearanceStore: SettingsPreferenceStore())

    await model.loadProfileActivity()
    #expect(model.gameActivity.latestAnalysis == Date(timeIntervalSince1970: 30))
    #expect(model.gameActivity.nextReanalysis == Date(timeIntervalSince1970: 60))
    #expect(model.creatorActivity.latestAnalysis == Date(timeIntervalSince1970: 20))
    #expect(model.creatorActivity.nextReanalysis == Date(timeIntervalSince1970: 50))
    #expect(
      await api.profileCalls == [
        ProfileCall(type: .game, query: "", onlyCollection: false, cursor: nil, limit: 100),
        ProfileCall(
          type: .game, query: "", onlyCollection: false, cursor: "game opaque +/", limit: 100),
        ProfileCall(type: .creator, query: "", onlyCollection: false, cursor: nil, limit: 100),
      ])

    await model.loadProfileActivity()
    #expect(model.gameActivity.latestAnalysis == nil)
    #expect(model.activityError(for: .game) == "Profile activity is unavailable.")

    await model.loadReanalysis()
    model.updateReanalysis(gameIntervalDays: 35, creatorIntervalDays: 15)
    await model.saveReanalysis()
    #expect(model.sharedSettings == canonical)
  }

  @MainActor
  @Test func workspaceMetadataAndLocalDisconnectStayOfflineSafeSingleFlightAndSecretFree() async {
    let disconnectGate = SettingsGate<Void>()
    let probe = SettingsDisconnectProbe(gate: disconnectGate)
    let api = SettingsAPI()
    let model = SettingsModel(
      api: api, appearanceStore: SettingsPreferenceStore(), workspaceStatus: "Offline",
      apiBaseURL: "https://internal.example.test", appVersion: "15.0-canary",
      disconnect: { await probe.disconnect() })

    #expect(model.workspaceStatus == "Offline")
    #expect(model.apiBaseURL == "https://internal.example.test")
    #expect(model.appVersion == "15.0-canary")
    let disconnect = Task { await model.disconnectThisMac() }
    #expect(await disconnectGate.waitUntilEntered())
    await model.disconnectThisMac()
    #expect(await probe.count == 1)
    #expect(model.isDisconnecting)
    disconnectGate.resume(.success(()))
    await disconnect.value
    #expect(!model.isDisconnecting)
    #expect(await api.totalCallCount == 0)

    let publicCopy = [
      model.smtpActionError, model.smtpLoadError, model.reanalysisLoadError,
      model.reanalysisActionError,
      model.connectionError(for: .steam), model.connectionError(for: .youtube),
      model.connectionError(for: .deepSeek),
    ].compactMap { $0 }.joined(separator: " ")
    let exposesSMTP = publicCopy.contains(smtpCanary)
    let exposesService = publicCopy.contains(serviceCanary)
    #expect(!exposesSMTP)
    #expect(!exposesService)
  }
}

private final class SettingsObservationProbe: @unchecked Sendable {
  private let lock = NSLock()
  private var changed = false

  var didChange: Bool {
    lock.withLock { changed }
  }

  func markChanged() {
    lock.withLock { changed = true }
  }
}

@MainActor
private final class SettingsPreferenceStore: AppearancePreferenceStoring {
  private var values: [String: String]

  init(values: [String: String] = [:]) { self.values = values }

  func string(forKey key: String) -> String? { values[key] }
  func set(_ value: String, forKey key: String) { values[key] = value }
  func value(forKey key: String) -> String? { values[key] }
}

private struct ProfileCall: Sendable, Equatable {
  let type: ProfileType
  let query: String
  let onlyCollection: Bool
  let cursor: String?
  let limit: Int
}

private struct ConnectionReplaceCall: Sendable, Equatable {
  let service: ConnectionService
  let secret: String
}

private enum SettingsOutcome<Value: Sendable>: Sendable {
  case value(Value)
  case failure(APIError)
  case gated(SettingsGate<Value>)
}

private final class SettingsGate<Value: Sendable>: @unchecked Sendable {
  private let lock = NSLock()
  private var continuation: CheckedContinuation<Result<Value, APIError>, Never>?
  private var entered = false

  func wait() async -> Result<Value, APIError> {
    await withCheckedContinuation { continuation in
      lock.withLock {
        entered = true
        self.continuation = continuation
      }
    }
  }

  func waitUntilEntered() async -> Bool {
    for _ in 0..<1_000 {
      if lock.withLock({ entered }) { return true }
      await Task.yield()
    }
    return lock.withLock { entered }
  }

  func resume(_ result: Result<Value, APIError>) {
    let pending = lock.withLock {
      let pending = continuation
      continuation = nil
      return pending
    }
    pending?.resume(returning: result)
  }
}

private actor SettingsDisconnectProbe {
  private(set) var count = 0
  let gate: SettingsGate<Void>

  init(gate: SettingsGate<Void>) { self.gate = gate }

  func disconnect() async {
    count += 1
    _ = await gate.wait()
  }
}

private actor SettingsAPI: APIService {
  private var smtpLoadOutcomes: [SettingsOutcome<SMTPSettingsStatus>]
  private var smtpSaveOutcomes: [SettingsOutcome<SMTPSettingsStatus>]
  private var smtpTestOutcomes: [SettingsOutcome<ConnectionTestResult>]
  private var smtpSendOutcomes: [SettingsOutcome<ConnectionTestResult>]
  private var connectionLoadOutcomes: [SettingsOutcome<ConnectionStatus>]
  private var connectionReplaceOutcomes: [SettingsOutcome<ConnectionStatus>]
  private var connectionTestOutcomes: [SettingsOutcome<ConnectionTestResult>]
  private var sharedLoadOutcomes: [SettingsOutcome<SharedSettings>]
  private var sharedSaveOutcomes: [SettingsOutcome<SharedSettings>]
  private var profileOutcomes: [SettingsOutcome<ProfileCardPage>]

  private(set) var smtpLoadCalls = 0
  private(set) var smtpSaveCalls: [SMTPSettingsDraft] = []
  private(set) var smtpTestCalls = 0
  private(set) var smtpSendCalls: [String] = []
  private(set) var connectionLoadCalls: [ConnectionService] = []
  private(set) var connectionReplaceCalls: [ConnectionReplaceCall] = []
  private(set) var connectionTestCalls: [ConnectionService] = []
  private(set) var sharedLoadCalls = 0
  private(set) var sharedSaveCalls: [ReanalysisDraft] = []
  private(set) var profileCalls: [ProfileCall] = []

  var totalCallCount: Int {
    smtpLoadCalls + smtpSaveCalls.count + smtpTestCalls + smtpSendCalls.count
      + connectionLoadCalls.count + connectionReplaceCalls.count + connectionTestCalls.count
      + sharedLoadCalls + sharedSaveCalls.count + profileCalls.count
  }

  init(
    smtpLoadOutcomes: [SettingsOutcome<SMTPSettingsStatus>] = [],
    smtpSaveOutcomes: [SettingsOutcome<SMTPSettingsStatus>] = [],
    smtpTestOutcomes: [SettingsOutcome<ConnectionTestResult>] = [],
    smtpSendOutcomes: [SettingsOutcome<ConnectionTestResult>] = [],
    connectionLoadOutcomes: [SettingsOutcome<ConnectionStatus>] = [],
    connectionReplaceOutcomes: [SettingsOutcome<ConnectionStatus>] = [],
    connectionTestOutcomes: [SettingsOutcome<ConnectionTestResult>] = [],
    sharedLoadOutcomes: [SettingsOutcome<SharedSettings>] = [],
    sharedSaveOutcomes: [SettingsOutcome<SharedSettings>] = [],
    profileOutcomes: [SettingsOutcome<ProfileCardPage>] = []
  ) {
    self.smtpLoadOutcomes = smtpLoadOutcomes
    self.smtpSaveOutcomes = smtpSaveOutcomes
    self.smtpTestOutcomes = smtpTestOutcomes
    self.smtpSendOutcomes = smtpSendOutcomes
    self.connectionLoadOutcomes = connectionLoadOutcomes
    self.connectionReplaceOutcomes = connectionReplaceOutcomes
    self.connectionTestOutcomes = connectionTestOutcomes
    self.sharedLoadOutcomes = sharedLoadOutcomes
    self.sharedSaveOutcomes = sharedSaveOutcomes
    self.profileOutcomes = profileOutcomes
  }

  func smtpSettings() async throws -> SMTPSettingsStatus {
    smtpLoadCalls += 1
    return try await resolve(smtpLoadOutcomes.removeFirst())
  }

  func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    smtpSaveCalls.append(draft)
    return try await resolve(smtpSaveOutcomes.removeFirst())
  }

  func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws -> ConnectionTestResult {
    #expect(draft == nil)
    smtpTestCalls += 1
    return try await resolve(smtpTestOutcomes.removeFirst())
  }

  func sendSMTPTest(to email: String) async throws -> ConnectionTestResult {
    smtpSendCalls.append(email)
    return try await resolve(smtpSendOutcomes.removeFirst())
  }

  func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    connectionLoadCalls.append(service)
    return try await resolve(connectionLoadOutcomes.removeFirst())
  }

  func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  {
    connectionReplaceCalls.append(ConnectionReplaceCall(service: service, secret: secret))
    return try await resolve(connectionReplaceOutcomes.removeFirst())
  }

  func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult {
    connectionTestCalls.append(service)
    return try await resolve(connectionTestOutcomes.removeFirst())
  }

  func sharedSettings() async throws -> SharedSettings {
    sharedLoadCalls += 1
    return try await resolve(sharedLoadOutcomes.removeFirst())
  }

  func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    sharedSaveCalls.append(draft)
    return try await resolve(sharedSaveOutcomes.removeFirst())
  }

  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage {
    profileCalls.append(
      ProfileCall(
        type: type, query: query, onlyCollection: onlyCollection, cursor: cursor, limit: limit))
    return try await resolve(profileOutcomes.removeFirst())
  }

  private func resolve<Value: Sendable>(_ outcome: SettingsOutcome<Value>) async throws -> Value {
    switch outcome {
    case .value(let value): return value
    case .failure(let error): throw error
    case .gated(let gate): return try await gate.wait().get()
    }
  }
}

extension APIService {
  fileprivate func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  fileprivate func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage
  {
    fatalError("unused")
  }
  fileprivate func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String)
    async throws -> AnalysisSubmission
  { fatalError("unused") }
  fileprivate func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    fatalError("unused")
  }
  fileprivate func profile(type: ProfileType, id: UUID) async throws -> Profile {
    fatalError("unused")
  }
  fileprivate func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws
    -> ProfileCard
  { fatalError("unused") }
  fileprivate func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  { fatalError("unused") }
  fileprivate func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func listMatches(cursor: String?) async throws -> MatchTaskPage {
    fatalError("unused")
  }
  fileprivate func match(id: UUID) async throws -> MatchResult { fatalError("unused") }
  fileprivate func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func listCampaigns(cursor: String?) async throws -> CampaignPage {
    fatalError("unused")
  }
  fileprivate func campaign(id: UUID) async throws -> OutreachCampaign { fatalError("unused") }
  fileprivate func listTemplates() async throws -> [OutreachTemplate] { fatalError("unused") }
  fileprivate func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func duplicateTemplate(id: UUID) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func deleteTemplate(id: UUID) async throws { fatalError("unused") }
  fileprivate func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    fatalError("unused")
  }
  fileprivate func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    fatalError("unused")
  }
  fileprivate func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  { fatalError("unused") }
  fileprivate func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
}

private func smtpStatus(
  configured: Bool,
  host: String? = nil,
  port: Int? = 587,
  encryption: SMTPEncryption? = .startTLS,
  username: String? = "mailer@company.test",
  fromName: String? = "Creator Team",
  replyTo: String? = "reply@company.test",
  rate: Int = 30,
  testStatus: ConnectionTestStatus = .notTested,
  at: TimeInterval? = nil
) -> SMTPSettingsStatus {
  SMTPSettingsStatus(
    configured: configured, host: host, port: port, encryption: encryption, username: username,
    fromName: fromName, replyTo: replyTo, emailsPerMinute: rate, lastTestStatus: testStatus,
    lastTestedAt: at.map(Date.init(timeIntervalSince1970:)))
}

private func connection(
  _ service: ConnectionService,
  configured: Bool = false,
  status: ConnectionTestStatus = .notTested,
  at: TimeInterval? = nil
) -> ConnectionStatus {
  ConnectionStatus(
    service: service, configured: configured, lastTestStatus: status,
    lastTestedAt: at.map(Date.init(timeIntervalSince1970:)))
}

private func testResult(_ status: ConnectionTestStatus, at: TimeInterval) -> ConnectionTestResult {
  ConnectionTestResult(
    succeeded: status == .success, status: status, testedAt: Date(timeIntervalSince1970: at))
}

private func id(_ suffix: Int) -> UUID {
  UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))!
}

private func gameCard(id: UUID, last: TimeInterval?, next: TimeInterval?) -> GameProfileCard {
  GameProfileCard(
    id: id, name: "Game", steamAppID: "730", canonicalURL: "https://example.test/game",
    favorite: false, currentFacts: [:], brief: [:], sourceStatus: [:],
    lastAnalyzedAt: last.map(Date.init(timeIntervalSince1970:)),
    nextAnalysisAt: next.map(Date.init(timeIntervalSince1970:)))
}

private func creatorCard(id: UUID, last: TimeInterval?, next: TimeInterval?) -> CreatorProfileCard {
  CreatorProfileCard(
    id: id, name: "Creator", youtubeChannelID: "UC-canary",
    canonicalURL: "https://example.test/creator", favorite: false, currentFacts: [:], brief: [:],
    sourceStatus: [:], lastAnalyzedAt: last.map(Date.init(timeIntervalSince1970:)),
    nextAnalysisAt: next.map(Date.init(timeIntervalSince1970:)), contact: nil)
}
