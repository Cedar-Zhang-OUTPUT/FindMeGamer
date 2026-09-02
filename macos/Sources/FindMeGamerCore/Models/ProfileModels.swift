import Foundation

public enum ProfileType: String, Sendable, Equatable, Hashable, CaseIterable {
  case game
  case creator

  public var displayName: String { self == .game ? "Game" : "Creator" }
}

public enum ContactAvailability: String, Sendable, Equatable, Hashable {
  case manual
  case discovered
  case unavailable

  public var displayName: String {
    switch self {
    case .manual: "Manual"
    case .discovered: "Discovered"
    case .unavailable: "Unavailable"
    }
  }
}

public struct CreatorContact: Sendable, Equatable, Hashable {
  public let email: String
  public let availability: ContactAvailability
  public let source: String
  public let sourceURL: String?
  public let validationState: String
}

public struct GameProfileCard: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let name: String
  public let steamAppID: String
  public let canonicalURL: String
  public let favorite: Bool
  public let currentFacts: JSONObject
  public let brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
}

public struct CreatorProfileCard: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let name: String
  public let youtubeChannelID: String
  public let canonicalURL: String
  public let favorite: Bool
  public let currentFacts: JSONObject
  public let brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
  public let contact: CreatorContact?

  public var contactAvailability: ContactAvailability {
    contact?.availability ?? .unavailable
  }
}

public struct GameProfile: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let name: String
  public let steamAppID: String
  public let canonicalURL: String
  public let favorite: Bool
  public let currentFacts: JSONObject
  public let brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
  public let analysis: JSONObject
  public let modelMetadata: JSONObject
  public let promptMetadata: JSONObject
}

public struct CreatorProfile: Identifiable, Sendable, Equatable {
  public let id: UUID
  public let name: String
  public let youtubeChannelID: String
  public let canonicalURL: String
  public let favorite: Bool
  public let currentFacts: JSONObject
  public let brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
  public let contact: CreatorContact?
  public let manualNotes: String?
  public let analysis: JSONObject
  public let modelMetadata: JSONObject
  public let promptMetadata: JSONObject

  public var contactAvailability: ContactAvailability {
    contact?.availability ?? .unavailable
  }
}

public enum ProfileCard: Identifiable, Sendable, Equatable {
  case game(GameProfileCard)
  case creator(CreatorProfileCard)

  public var id: UUID {
    switch self {
    case .game(let value): value.id
    case .creator(let value): value.id
    }
  }
}

public enum Profile: Identifiable, Sendable, Equatable {
  case game(GameProfile)
  case creator(CreatorProfile)

  public var id: UUID {
    switch self {
    case .game(let value): value.id
    case .creator(let value): value.id
    }
  }
}

public struct ProfileCardPage: Sendable, Equatable {
  public let items: [ProfileCard]
  public let nextCursor: String?
}
