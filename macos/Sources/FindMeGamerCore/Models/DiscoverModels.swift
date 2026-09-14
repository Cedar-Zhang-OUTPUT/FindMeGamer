import Foundation

public struct DiscoverGame: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID?
  public let name: String
  public let url: String
}
public struct DiscoverGamePage: Sendable {
  public let items: [DiscoverGame]
  public let nextCursor: String?
}
public struct DiscoverCapability: Identifiable, Sendable, Equatable {
  public var id: String { platform }
  public let platform: String
  public let available: Bool
  public let reason: String?
  public var title: String { CreatorPlatform.title(platform) }
}
public enum CreatorPlatform {
  public static func title(_ value: String) -> String {
    switch value.lowercased() {
    case "youtube": "YouTube"
    case "x", "twitter": "X"
    case "instagram": "Instagram"
    case "twitch": "Twitch"
    default: value.capitalized
    }
  }
  public static func isX(url: String) -> Bool {
    ["x.com", "www.x.com", "twitter.com", "www.twitter.com"].contains(
      URL(string: url)?.host?.lowercased() ?? "")
  }
}
public struct DiscoverConditions: Sendable, Equatable, Hashable {
  public var platforms: Set<String> = ["youtube"]
  public var language = ""
  public var minimumFollowers = ""
  public var maximumFollowers = ""
  public var keywords = ""
  public init() {}
  public var isValid: Bool {
    func valid(_ text: String) -> Bool {
      text.isEmpty || Int64(text).map { $0 >= 0 && $0 <= 1_000_000_000_000 } == true
    }
    return !platforms.isEmpty && valid(minimumFollowers) && valid(maximumFollowers)
      && (Int64(minimumFollowers) ?? 0) <= (Int64(maximumFollowers) ?? 1_000_000_000_000)
      && keywords.count <= 500
  }
}
public struct DiscoverCandidate: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let platform: String
  public let accountID: String
  public let name: String
  public let url: String
  public let inLibrary: Bool
}
public struct DiscoverRecord: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let gameID: UUID?
  public let gameName: String
  public let status: String
  public let stage: String?
  public let candidates: [DiscoverCandidate]
  public let issues: [String]
  public let createdAt: Date
  public var isActive: Bool { status == "queued" || status == "running" }
  public var stageTitle: String {
    switch stage {
    case "preparing_game": "Preparing game"
    case "finding_creators": "Finding creators"
    default: status.capitalized
    }
  }
}
public struct DiscoverSummary: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let gameName: String
  public let status: String
  public let candidateCount: Int
  public let createdAt: Date
}
public struct DiscoverPage: Sendable {
  public let items: [DiscoverSummary]
  public let nextCursor: String?
}
public enum DiscoverAnalysisMode: String, Sendable, Hashable {
  case analyze
  case analyzeAndMatch = "analyze_and_match"
}
public struct DiscoverBatchItem: Identifiable, Sendable, Equatable {
  public var id: UUID { candidateID }
  public let candidateID: UUID
  public let status: String
  public let reused: Bool
  public let error: String?
}
public struct DiscoverBatch: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let discoverID: UUID
  public let mode: DiscoverAnalysisMode
  public let status: String
  public let items: [DiscoverBatchItem]
  public let matchID: UUID?
  public let error: String?
  public var isActive: Bool { status == "queued" || status == "running" }
  public var reusedCount: Int { items.filter(\.reused).count }
  public var analyzingCount: Int {
    items.filter { $0.status == "queued" || $0.status == "running" }.count
  }
  public var succeededCount: Int { items.filter { $0.status == "succeeded" && !$0.reused }.count }
  public var failedCount: Int { items.filter { $0.status == "failed" }.count }
}
