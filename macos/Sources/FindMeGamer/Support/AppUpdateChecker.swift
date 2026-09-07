import Foundation
import Observation

/// SemVer precedence, without integer overflow or build-metadata ordering.
struct AppSemanticVersion: Comparable, Sendable {
  let major: String
  let minor: String
  let patch: String
  let prerelease: [String]
  let buildMetadata: [String]

  init?(_ value: String) {
    guard !value.isEmpty, value.utf8.count <= 128 else { return nil }
    let buildParts = value.split(separator: "+", omittingEmptySubsequences: false)
    guard buildParts.count <= 2 else { return nil }
    let versionPart = String(buildParts[0])
    let core: String
    let prerelease: [String]
    if let separator = versionPart.firstIndex(of: "-") {
      core = String(versionPart[..<separator])
      prerelease = versionPart[versionPart.index(after: separator)...]
        .split(separator: ".", omittingEmptySubsequences: false).map(String.init)
      guard Self.validIdentifiers(prerelease, leadingZeroesAllowed: false) else { return nil }
    } else {
      core = versionPart
      prerelease = []
    }
    let numbers = core.split(separator: ".", omittingEmptySubsequences: false).map(String.init)
    guard numbers.count == 3, numbers.allSatisfy(Self.validCoreNumber) else { return nil }
    let metadata =
      buildParts.count == 2
      ? buildParts[1].split(separator: ".", omittingEmptySubsequences: false).map(String.init) : []
    guard buildParts.count == 1 || Self.validIdentifiers(metadata, leadingZeroesAllowed: true)
    else {
      return nil
    }
    major = numbers[0]
    minor = numbers[1]
    patch = numbers[2]
    self.prerelease = prerelease
    buildMetadata = metadata
  }

  var coreVersion: String { "\(major).\(minor).\(patch)" }
  var isPlainRelease: Bool { prerelease.isEmpty && buildMetadata.isEmpty }

  static func == (lhs: Self, rhs: Self) -> Bool {
    lhs.major == rhs.major && lhs.minor == rhs.minor && lhs.patch == rhs.patch
      && lhs.prerelease == rhs.prerelease
  }

  static func < (lhs: Self, rhs: Self) -> Bool {
    for (left, right) in zip([lhs.major, lhs.minor, lhs.patch], [rhs.major, rhs.minor, rhs.patch]) {
      if left != right { return numericLess(left, right) }
    }
    if lhs.prerelease.isEmpty { return false }
    if rhs.prerelease.isEmpty { return true }
    for (left, right) in zip(lhs.prerelease, rhs.prerelease) where left != right {
      let leftNumeric = isNumeric(left)
      let rightNumeric = isNumeric(right)
      if leftNumeric && rightNumeric { return numericLess(left, right) }
      if leftNumeric != rightNumeric { return leftNumeric }
      return left.lexicographicallyPrecedes(right)
    }
    return lhs.prerelease.count < rhs.prerelease.count
  }

  private static func numericLess(_ lhs: String, _ rhs: String) -> Bool {
    lhs.count == rhs.count ? lhs.lexicographicallyPrecedes(rhs) : lhs.count < rhs.count
  }

  private static func isNumeric(_ value: String) -> Bool {
    !value.isEmpty && value.utf8.allSatisfy { (48...57).contains($0) }
  }

  private static func validCoreNumber(_ value: String) -> Bool {
    isNumeric(value) && (value.count == 1 || value.first != "0")
  }

  private static func validIdentifiers(_ values: [String], leadingZeroesAllowed: Bool) -> Bool {
    !values.isEmpty
      && values.allSatisfy { value in
        !value.isEmpty
          && value.utf8.allSatisfy {
            (48...57).contains($0) || (65...90).contains($0) || (97...122).contains($0) || $0 == 45
          } && (leadingZeroesAllowed || !isNumeric(value) || validCoreNumber(value))
      }
  }
}

enum AppUpdateFeed {
  // Owner-approved static feed. No workspace API or credentials are involved.
  static let isEnabled = true
  static let manifestURL = URL(string: "https://44.233.174.193/updates/macos.json")!
  static let releasesURL = URL(
    string: "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases")!
  static let maximumResponseBytes = 32_768

  static func validatedReleasePage(_ url: URL) -> URL? {
    guard let parts = URLComponents(url: url, resolvingAgainstBaseURL: false),
      parts.scheme == "https", parts.host?.lowercased() == "github.com",
      parts.user == nil, parts.password == nil, parts.port == nil,
      parts.query == nil, parts.fragment == nil
    else { return nil }
    let prefix = "/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/"
    guard parts.percentEncodedPath.hasPrefix(prefix) else { return nil }
    let tag = String(parts.percentEncodedPath.dropFirst(prefix.count))
    let version = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
    guard let parsed = AppSemanticVersion(version), parsed.buildMetadata.isEmpty else { return nil }
    if !parsed.prerelease.isEmpty {
      guard parsed.prerelease.count == 2, parsed.prerelease[0] == "internal",
        let first = parsed.prerelease[1].utf8.first, (49...57).contains(first),
        parsed.prerelease[1].utf8.allSatisfy({ (48...57).contains($0) })
      else { return nil }
    }
    return URL(string: "https://github.com\(prefix)\(tag)")
  }
}

struct AppUpdateRelease: Codable, Equatable, Sendable {
  let version: String
  let releasePageURL: URL

  var validated: Self? {
    guard let parsed = AppSemanticVersion(version), parsed.isPlainRelease,
      let page = AppUpdateFeed.validatedReleasePage(releasePageURL)
    else { return nil }
    let tag = page.lastPathComponent
    let tagVersion = AppSemanticVersion(tag.hasPrefix("v") ? String(tag.dropFirst()) : tag)
    guard tagVersion?.coreVersion == version else { return nil }
    return Self(version: version, releasePageURL: page)
  }
}

protocol AppUpdateSource: Sendable {
  func latestRelease() async throws -> AppUpdateRelease
}

enum AppUpdateError: Error, Equatable {
  case unavailable
  case rateLimited
  case invalidResponse
  case oversizedResponse
  case untrustedResponse

  var message: String {
    switch self {
    case .unavailable: "The update service is unavailable. Try again later."
    case .rateLimited: "Too many update checks. Try again later."
    case .invalidResponse: "The update information could not be verified."
    case .oversizedResponse: "The update response exceeded the allowed size."
    case .untrustedResponse: "The update service returned an untrusted address."
    }
  }
}

/// The feed is independent of the private GitHub repository and carries no credentials.
struct StaticManifestUpdateSource: AppUpdateSource {
  private struct Manifest: Decodable {
    let schemaVersion: Int
    let version: String
    let releasePageURL: URL

    enum CodingKeys: String, CodingKey {
      case schemaVersion = "schema_version"
      case version
      case releasePageURL = "release_page_url"
    }
  }

  func latestRelease() async throws -> AppUpdateRelease {
    let session = URLSession(
      configuration: Self.configuration(), delegate: NoUpdateRedirects(), delegateQueue: nil)
    defer { session.invalidateAndCancel() }
    let (bytes, response) = try await session.bytes(for: Self.request())
    try Self.validate(response)
    return try Self.decode(try await Self.boundedBody(bytes))
  }

  static func configuration() -> URLSessionConfiguration {
    let configuration = URLSessionConfiguration.ephemeral
    configuration.httpCookieStorage = nil
    configuration.urlCredentialStorage = nil
    configuration.httpShouldSetCookies = false
    configuration.timeoutIntervalForRequest = 15
    configuration.timeoutIntervalForResource = 20
    configuration.waitsForConnectivity = false
    return configuration
  }

  static func request() -> URLRequest {
    var request = URLRequest(url: AppUpdateFeed.manifestURL)
    request.httpMethod = "GET"
    request.httpShouldHandleCookies = false
    request.timeoutInterval = 15
    request.setValue("application/json", forHTTPHeaderField: "Accept")
    request.setValue("FindMeGamer-UpdateChecker", forHTTPHeaderField: "User-Agent")
    request.cachePolicy = .reloadIgnoringLocalCacheData
    return request
  }

  static func boundedBody<Bytes: AsyncSequence>(_ bytes: Bytes) async throws -> Data
  where Bytes.Element == UInt8 {
    var body = Data()
    for try await byte in bytes {
      guard body.count < AppUpdateFeed.maximumResponseBytes else {
        throw AppUpdateError.oversizedResponse
      }
      body.append(byte)
    }
    return body
  }

  static func validate(_ response: URLResponse) throws {
    guard response.url == AppUpdateFeed.manifestURL, let http = response as? HTTPURLResponse else {
      throw AppUpdateError.untrustedResponse
    }
    guard http.statusCode == 200 else {
      throw http.statusCode == 429 ? AppUpdateError.rateLimited : AppUpdateError.unavailable
    }
    guard response.expectedContentLength <= Int64(AppUpdateFeed.maximumResponseBytes) else {
      throw AppUpdateError.oversizedResponse
    }
  }

  static func decode(_ data: Data) throws -> AppUpdateRelease {
    guard data.count <= AppUpdateFeed.maximumResponseBytes else {
      throw AppUpdateError.oversizedResponse
    }
    guard let manifest = try? JSONDecoder().decode(Manifest.self, from: data),
      manifest.schemaVersion == 1,
      let release = AppUpdateRelease(
        version: manifest.version, releasePageURL: manifest.releasePageURL
      ).validated
    else { throw AppUpdateError.invalidResponse }
    return release
  }
}

final class NoUpdateRedirects: NSObject, URLSessionTaskDelegate, Sendable {
  func urlSession(
    _ session: URLSession, task: URLSessionTask,
    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
    completionHandler: @escaping @Sendable (URLRequest?) -> Void
  ) {
    completionHandler(nil)
  }
}

enum AppUpdateCheckState: Equatable {
  case idle, checking, checked, developmentBuild, disabled
  case failed(String)
}

@MainActor
@Observable
final class AppUpdateChecker {
  static let automaticInterval: TimeInterval = 24 * 60 * 60
  let installedVersion: String?
  private(set) var availableRelease: AppUpdateRelease?
  private(set) var state = AppUpdateCheckState.idle
  private(set) var lastCheckedAt: Date?
  var automaticallyChecks: Bool {
    didSet { defaults.set(automaticallyChecks, forKey: Self.automaticKey) }
  }
  let sourceEnabled: Bool

  @ObservationIgnored private let source: any AppUpdateSource
  @ObservationIgnored private let defaults: UserDefaults
  @ObservationIgnored private let now: @Sendable () -> Date
  @ObservationIgnored private var lastAttemptAt: Date?
  private static let automaticKey = "app-updates.automatic"
  private static let attemptKey = "app-updates.last-attempt"
  private static let checkedKey = "app-updates.last-checked"
  private static let releaseKey = "app-updates.available-release"

  init(
    installedVersion: String? = Bundle.main.object(
      forInfoDictionaryKey: "CFBundleShortVersionString") as? String,
    source: any AppUpdateSource = StaticManifestUpdateSource(),
    sourceEnabled: Bool = AppUpdateFeed.isEnabled,
    defaults: UserDefaults = .standard,
    now: @escaping @Sendable () -> Date = Date.init
  ) {
    self.installedVersion = installedVersion
    self.source = source
    self.sourceEnabled = sourceEnabled
    self.defaults = defaults
    self.now = now
    automaticallyChecks = defaults.object(forKey: Self.automaticKey) as? Bool ?? true
    lastAttemptAt = defaults.object(forKey: Self.attemptKey) as? Date
    lastCheckedAt = defaults.object(forKey: Self.checkedKey) as? Date
    if let data = defaults.data(forKey: Self.releaseKey),
      let cached = try? JSONDecoder().decode(AppUpdateRelease.self, from: data),
      let release = cached.validated,
      let current = installedVersion.flatMap(AppSemanticVersion.init),
      let newer = AppSemanticVersion(release.version), newer > current
    {
      availableRelease = release
    }
    if !sourceEnabled {
      state = .disabled
    } else if installedVersion.flatMap(AppSemanticVersion.init) == nil {
      state = .developmentBuild
    }
  }

  var isChecking: Bool { state == .checking }

  func checkAutomaticallyIfNeeded() async {
    guard automaticallyChecks else { return }
    if let lastAttemptAt {
      let age = now().timeIntervalSince(lastAttemptAt)
      guard age < 0 || age >= Self.automaticInterval else { return }
    }
    await check()
  }

  func check() async {
    guard !isChecking else { return }
    guard sourceEnabled else {
      state = .disabled
      return
    }
    guard let current = installedVersion.flatMap(AppSemanticVersion.init) else {
      state = .developmentBuild
      return
    }
    let previousState = state
    let previousAttempt = lastAttemptAt
    state = .checking
    lastAttemptAt = now()
    defaults.set(lastAttemptAt, forKey: Self.attemptKey)
    do {
      let received = try await source.latestRelease()
      try Task.checkCancellation()
      guard let release = received.validated, let version = AppSemanticVersion(release.version)
      else {
        throw AppUpdateError.invalidResponse
      }
      availableRelease = version > current ? release : nil
      lastCheckedAt = now()
      defaults.set(lastCheckedAt, forKey: Self.checkedKey)
      if let availableRelease {
        defaults.set(try JSONEncoder().encode(availableRelease), forKey: Self.releaseKey)
      } else {
        defaults.removeObject(forKey: Self.releaseKey)
      }
      state = .checked
    } catch  where error is CancellationError || (error as? URLError)?.code == .cancelled {
      state = previousState
      lastAttemptAt = previousAttempt
      defaults.set(previousAttempt, forKey: Self.attemptKey)
    } catch {
      // A failed refresh never erases a previously verified download entry.
      state = .failed(
        (error as? AppUpdateError)?.message
          ?? "Could not check for updates. Check your connection and try again.")
    }
  }
}
