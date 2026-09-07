import Foundation
import Testing

@testable import FindMeGamer

@Suite struct AppSemanticVersionTests {
  @Test func numericalPartsDoNotUseLexicographicalOrFloatingPointOrder() throws {
    #expect(try #require(AppSemanticVersion("0.1.9")) < #require(AppSemanticVersion("0.1.10")))
    #expect(try #require(AppSemanticVersion("1.99.99")) < #require(AppSemanticVersion("2.0.0")))
    #expect(
      try #require(AppSemanticVersion("1.0.999999999999999999999999")) < #require(
        AppSemanticVersion("1.0.1000000000000000000000000")))
  }

  @Test func semverPrereleasePrecedenceMatchesTheSpecification() throws {
    let ordered = [
      "1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2",
      "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0",
    ]
    let versions = try ordered.map { try #require(AppSemanticVersion($0)) }
    for (older, newer) in zip(versions, versions.dropFirst()) { #expect(older < newer) }
    #expect(AppSemanticVersion("1.0.0+build.1") == AppSemanticVersion("1.0.0+build.2"))
    #expect(AppSemanticVersion("1.0.0-rc.1+build.1") == AppSemanticVersion("1.0.0-rc.1+build.2"))
  }

  @Test func malformedVersionsAndNumericLeadingZeroesAreRejected() {
    for invalid in [
      "", "v1.0.0", "1.0", "01.0.0", "1.01.0", "1.0.01", "1.0.-1", "1.0.0-", "1.0.0-rc..1",
      "1.0.0-01", "1.0.0+", "1.0.0+a+b", "1.0.0 rc", " 1.0.0", "1.0.0\n", "1.0.0-α",
    ] {
      #expect(AppSemanticVersion(invalid) == nil, "Accepted malformed version: \(invalid)")
    }
    #expect(AppSemanticVersion("1.0.0+001") != nil)
    #expect(AppSemanticVersion("1.0.0-internal.1") != nil)
  }
}

@Suite struct AppUpdateSourcePolicyTests {
  @Test func internalTagCanIdentifyANumericClientRelease() throws {
    let release = try StaticManifestUpdateSource.decode(manifest(version: "0.1.3"))
    #expect(release.version == "0.1.3")
    #expect(release.releasePageURL.absoluteString == releasePage(version: "0.1.3"))
    for tag in ["0.1.3", "v0.1.3", "0.1.3-internal.1", "v0.1.3-internal.10"] {
      let page = "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/\(tag)"
      #expect(
        try StaticManifestUpdateSource.decode(manifest(version: "0.1.3", page: page)).version
          == "0.1.3")
    }
    for tag in [
      "v0.1.3-rc.1", "v0.1.3-beta", "v0.1.3+build.1", "v0.1.3-internal.0", "v0.1.3-internal.01",
      "v0.1.3-internal.1.extra",
    ] {
      let page = "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/\(tag)"
      #expect(throws: AppUpdateError.invalidResponse) {
        try StaticManifestUpdateSource.decode(manifest(version: "0.1.3", page: page))
      }
    }
  }

  @Test func manifestRejectsUnknownSchemaPrereleaseVersionAndMismatchedTag() {
    for data in [
      manifest(version: "0.1.3", schema: 2),
      manifest(version: "0.1.3-rc.1"),
      manifest(version: "0.1.3+build.1"),
      manifest(version: "0.1.3", page: releasePage(version: "0.1.2")),
      Data("{}".utf8), Data("<html>Unavailable</html>".utf8),
    ] {
      #expect(throws: AppUpdateError.invalidResponse) {
        try StaticManifestUpdateSource.decode(data)
      }
    }
  }

  @Test func releaseLinksMustStayOnTheExactOfficialRepository() throws {
    #expect(
      AppUpdateFeed.validatedReleasePage(try #require(URL(string: releasePage(version: "0.1.3"))))
        != nil)
    for invalid in [
      "http://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3",
      "https://github.com.evil.test/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3",
      "https://evil.test/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3",
      "https://github.com/another-owner/FindMeGamer/releases/tag/v0.1.3",
      "https://github.com/Cedar-Zhang-OUTPUT/another-app/releases/tag/v0.1.3",
      "https://user:password@github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3",
      "https://github.com:444/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3",
      "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3?redirect=evil",
      "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3#download",
      "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3%2F..",
      "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v0.1.3/extra",
    ] {
      #expect(AppUpdateFeed.validatedReleasePage(try #require(URL(string: invalid))) == nil)
    }
  }

  @Test func responseMustBeSuccessfulBoundedAndFromThePinnedSource() throws {
    let success = try #require(
      HTTPURLResponse(
        url: AppUpdateFeed.manifestURL, statusCode: 200, httpVersion: nil, headerFields: nil))
    try StaticManifestUpdateSource.validate(success)
    let missing = try #require(
      HTTPURLResponse(
        url: AppUpdateFeed.manifestURL, statusCode: 404, httpVersion: nil, headerFields: nil))
    #expect(throws: AppUpdateError.unavailable) { try StaticManifestUpdateSource.validate(missing) }
    let limited = try #require(
      HTTPURLResponse(
        url: AppUpdateFeed.manifestURL, statusCode: 429, httpVersion: nil, headerFields: nil))
    #expect(throws: AppUpdateError.rateLimited) { try StaticManifestUpdateSource.validate(limited) }
    let foreign = try #require(
      HTTPURLResponse(
        url: URL(string: "https://evil.test/updates/macos.json")!, statusCode: 200,
        httpVersion: nil, headerFields: nil))
    #expect(throws: AppUpdateError.untrustedResponse) {
      try StaticManifestUpdateSource.validate(foreign)
    }
    let excessive = Data(repeating: 32, count: AppUpdateFeed.maximumResponseBytes + 1)
    #expect(throws: AppUpdateError.oversizedResponse) {
      try StaticManifestUpdateSource.decode(excessive)
    }
  }

  @Test func transportContainsNoCredentialsCookiesOrRedirectFallback() async throws {
    let request = StaticManifestUpdateSource.request()
    #expect(request.url == AppUpdateFeed.manifestURL)
    #expect(request.httpMethod == "GET")
    #expect(request.value(forHTTPHeaderField: "Authorization") == nil)
    #expect(request.value(forHTTPHeaderField: "Cookie") == nil)
    #expect(!request.httpShouldHandleCookies)
    #expect(request.timeoutInterval == 15)
    let configuration = StaticManifestUpdateSource.configuration()
    #expect(configuration.urlCredentialStorage == nil)
    #expect(configuration.httpCookieStorage == nil)
    #expect(!configuration.httpShouldSetCookies)
    #expect(!configuration.waitsForConnectivity)
    let session = URLSession(configuration: configuration)
    defer { session.invalidateAndCancel() }
    let task = session.dataTask(with: request)
    let redirect = try #require(
      HTTPURLResponse(
        url: AppUpdateFeed.manifestURL, statusCode: 302, httpVersion: nil, headerFields: nil))
    let destination: URLRequest? = await withCheckedContinuation { continuation in
      NoUpdateRedirects().urlSession(
        session, task: task, willPerformHTTPRedirection: redirect,
        newRequest: URLRequest(url: URL(string: "https://example.com/")!)
      ) {
        continuation.resume(returning: $0)
      }
    }
    #expect(destination == nil)
  }

  @Test func streamingBodyLimitDoesNotDependOnContentLength() async throws {
    let bytes = AsyncStream<UInt8> { continuation in
      for _ in 0...AppUpdateFeed.maximumResponseBytes { continuation.yield(32) }
      continuation.finish()
    }
    await #expect(throws: AppUpdateError.oversizedResponse) {
      try await StaticManifestUpdateSource.boundedBody(bytes)
    }
  }
}

@MainActor
@Suite struct AppUpdateCheckerTests {
  @Test func olderClientOffersTheUpdateButCurrentAndNewerClientsDoNot() async throws {
    for installed in ["0.1.2", "0.1.3", "0.1.4"] {
      let preferences = UpdateTestPreferences()
      defer { preferences.cleanUp() }
      let checker = AppUpdateChecker(
        installedVersion: installed, source: FixtureUpdateSource(release: try release()),
        sourceEnabled: true, defaults: preferences.defaults)
      await checker.check()
      #expect(checker.state == .checked)
      #expect((checker.availableRelease != nil) == (installed == "0.1.2"))
    }
  }

  @Test func automaticChecksAreDailyPersistedAndManualChecksBypassTheInterval() async throws {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let source = CountingUpdateSource(release: try release())
    let time = Date(timeIntervalSince1970: 1_800_000_000)
    let checker = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true,
      defaults: preferences.defaults, now: { time })
    await checker.checkAutomaticallyIfNeeded()
    await checker.checkAutomaticallyIfNeeded()
    #expect(await source.calls == 1)
    let restored = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true,
      defaults: preferences.defaults, now: { time })
    #expect(restored.availableRelease?.version == "0.1.3")
    await restored.checkAutomaticallyIfNeeded()
    #expect(await source.calls == 1)
    await restored.check()
    #expect(await source.calls == 2)
    let nextDay = time.addingTimeInterval(AppUpdateChecker.automaticInterval)
    let tomorrow = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true,
      defaults: preferences.defaults,
      now: { nextDay })
    await tomorrow.checkAutomaticallyIfNeeded()
    #expect(await source.calls == 3)
  }

  @Test func automaticChecksCanBeDisabledWithoutBlockingManualChecks() async throws {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let source = CountingUpdateSource(release: try release())
    let checker = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true, defaults: preferences.defaults
    )
    checker.automaticallyChecks = false
    await checker.checkAutomaticallyIfNeeded()
    #expect(await source.calls == 0)
    await checker.check()
    #expect(await source.calls == 1)
    let restored = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true, defaults: preferences.defaults
    )
    #expect(!restored.automaticallyChecks)
  }

  @Test func failedChecksDoNotClaimUpToDateOrEraseAnAvailableUpdate() async throws {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let source = CountingUpdateSource(release: try release())
    let checker = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true, defaults: preferences.defaults
    )
    await checker.check()
    let verifiedDate = checker.lastCheckedAt
    await source.fail()
    await checker.check()
    #expect(checker.state == .failed(AppUpdateError.unavailable.message))
    #expect(checker.availableRelease?.version == "0.1.3")
    #expect(checker.lastCheckedAt == verifiedDate)
    await checker.checkAutomaticallyIfNeeded()
    #expect(await source.calls == 2)
  }

  @Test func developmentBuildAndDisabledSourceNeverClaimAComparableVersion() async throws {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let source = CountingUpdateSource(release: try release())
    let development = AppUpdateChecker(
      installedVersion: nil, source: source, sourceEnabled: true, defaults: preferences.defaults)
    await development.check()
    #expect(development.state == .developmentBuild)
    let disabled = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: false,
      defaults: preferences.defaults)
    await disabled.check()
    #expect(disabled.state == .disabled)
    #expect(await source.calls == 0)
  }

  @Test func anUntrustedOrMismatchedInjectedReleaseIsRejectedAgainAtTheModelBoundary() async throws
  {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let invalid = AppUpdateRelease(
      version: "9.9.9", releasePageURL: try #require(URL(string: releasePage(version: "0.1.3"))))
    let checker = AppUpdateChecker(
      installedVersion: "0.1.2", source: FixtureUpdateSource(release: invalid), sourceEnabled: true,
      defaults: preferences.defaults)
    await checker.check()
    #expect(checker.state == .failed(AppUpdateError.invalidResponse.message))
    #expect(checker.availableRelease == nil)
  }

  @Test func simultaneousAutomaticAndManualChecksShareOneInFlightRequest() async throws {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let source = SuspendedUpdateSource(release: try release())
    let checker = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true,
      defaults: preferences.defaults)
    let first = Task { await checker.check() }
    await source.waitUntilEntered()
    #expect(checker.isChecking)
    await checker.check()
    await checker.checkAutomaticallyIfNeeded()
    #expect(await source.calls == 1)
    await source.finish()
    await first.value
    #expect(checker.state == .checked)
    #expect(checker.availableRelease?.version == "0.1.3")
  }

  @Test func cancelledCheckRestoresStateAndDoesNotBlockTheNextAutomaticAttempt() async throws {
    let preferences = UpdateTestPreferences()
    defer { preferences.cleanUp() }
    let time = Date(timeIntervalSince1970: 1_800_000_000)
    let source = SuspendedUpdateSource(release: try release())
    let checker = AppUpdateChecker(
      installedVersion: "0.1.2", source: source, sourceEnabled: true,
      defaults: preferences.defaults, now: { time })
    let pending = Task { await checker.checkAutomaticallyIfNeeded() }
    await source.waitUntilEntered()
    pending.cancel()
    await source.finish()
    await pending.value
    #expect(checker.state == .idle)
    #expect(checker.lastCheckedAt == nil)
    #expect(checker.availableRelease == nil)

    let nextSource = CountingUpdateSource(release: try release())
    let restored = AppUpdateChecker(
      installedVersion: "0.1.2", source: nextSource, sourceEnabled: true,
      defaults: preferences.defaults, now: { time })
    await restored.checkAutomaticallyIfNeeded()
    #expect(await nextSource.calls == 1)
    #expect(restored.state == .checked)
  }

  @Test(.enabled(if: ProcessInfo.processInfo.environment["FMG_VERIFY_LIVE_UPDATE"] == "1"))
  func liveApprovedManifestOffers013To012AndKeeps013Current() async throws {
    for installed in ["0.1.2", "0.1.3"] {
      let preferences = UpdateTestPreferences()
      defer { preferences.cleanUp() }
      let checker = AppUpdateChecker(
        installedVersion: installed, source: StaticManifestUpdateSource(), sourceEnabled: true,
        defaults: preferences.defaults)
      await checker.check()
      #expect(checker.state == .checked)
      if installed == "0.1.2" {
        let available = try #require(checker.availableRelease)
        #expect(available.version == "0.1.3")
        #expect(available.releasePageURL.absoluteString == releasePage(version: "0.1.3"))
      } else {
        #expect(checker.availableRelease == nil)
      }
    }
  }
}

private func releasePage(version: String) -> String {
  "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/v\(version)-internal.1"
}

private func manifest(version: String, schema: Int = 1, page: String? = nil) -> Data {
  try! JSONSerialization.data(withJSONObject: [
    "schema_version": schema, "version": version,
    "release_page_url": page ?? releasePage(version: version),
  ])
}

private func release() throws -> AppUpdateRelease {
  try StaticManifestUpdateSource.decode(manifest(version: "0.1.3"))
}

private struct FixtureUpdateSource: AppUpdateSource {
  let release: AppUpdateRelease
  func latestRelease() async throws -> AppUpdateRelease { release }
}

private actor CountingUpdateSource: AppUpdateSource {
  let release: AppUpdateRelease
  private(set) var calls = 0
  private var shouldFail = false
  init(release: AppUpdateRelease) { self.release = release }
  func fail() { shouldFail = true }
  func latestRelease() async throws -> AppUpdateRelease {
    calls += 1
    if shouldFail { throw AppUpdateError.unavailable }
    return release
  }
}

private actor SuspendedUpdateSource: AppUpdateSource {
  let release: AppUpdateRelease
  private(set) var calls = 0
  private var result: CheckedContinuation<AppUpdateRelease, Never>?
  private var entered: CheckedContinuation<Void, Never>?

  init(release: AppUpdateRelease) { self.release = release }

  func latestRelease() async throws -> AppUpdateRelease {
    calls += 1
    return await withCheckedContinuation { continuation in
      result = continuation
      entered?.resume()
      entered = nil
    }
  }

  func waitUntilEntered() async {
    if calls > 0 { return }
    await withCheckedContinuation { entered = $0 }
  }

  func finish() {
    result?.resume(returning: release)
    result = nil
  }
}

@MainActor
private struct UpdateTestPreferences {
  let name = "FindMeGamer.UpdateTests.\(UUID().uuidString)"
  let defaults: UserDefaults
  init() { defaults = UserDefaults(suiteName: name)! }
  func cleanUp() { defaults.removePersistentDomain(forName: name) }
}
