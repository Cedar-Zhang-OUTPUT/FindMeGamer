import Foundation

public enum ProfileType: String, Sendable, Equatable, Hashable, CaseIterable, Codable {
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
  public let purpose: String?

  public init(
    email: String, availability: ContactAvailability, source: String, sourceURL: String?,
    validationState: String, purpose: String? = nil
  ) {
    self.email = email
    self.availability = availability
    self.source = source
    self.sourceURL = sourceURL
    self.validationState = validationState
    self.purpose = purpose
  }
}

public struct GameProfileCard: Identifiable, Sendable, Equatable {
  public var profileRevision: Int = 0
  public var manualOverrides: [String: ProfileEditValue] = [:]
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
  public var profileRevision: Int = 0
  public var manualOverrides: [String: ProfileEditValue] = [:]
  public let id: UUID
  public let name: String
  public let youtubeChannelID: String?
  public var platformAccountID: String = ""
  public let canonicalURL: String
  public let favorite: Bool
  public let currentFacts: JSONObject
  public let brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
  public let contact: CreatorContact?
  public let contacts: [CreatorContact]

  public init(
    id: UUID, name: String, youtubeChannelID: String?, platformAccountID: String? = nil,
    canonicalURL: String, favorite: Bool,
    currentFacts: JSONObject, brief: JSONObject, sourceStatus: JSONObject,
    lastAnalyzedAt: Date?, nextAnalysisAt: Date?, contact: CreatorContact?,
    contacts: [CreatorContact]? = nil
  ) {
    self.id = id
    self.name = name
    self.youtubeChannelID = youtubeChannelID
    self.platformAccountID = platformAccountID ?? youtubeChannelID ?? ""
    self.canonicalURL = canonicalURL
    self.favorite = favorite
    self.currentFacts = currentFacts
    self.brief = brief
    self.sourceStatus = sourceStatus
    self.lastAnalyzedAt = lastAnalyzedAt
    self.nextAnalysisAt = nextAnalysisAt
    self.contact = contact
    self.contacts = contacts ?? contact.map { [$0] } ?? []
  }

  public var contactAvailability: ContactAvailability {
    contacts.first?.availability ?? .unavailable
  }
}

public struct GameProfile: Identifiable, Sendable, Equatable {
  public var profileRevision: Int = 0
  public var manualOverrides: [String: ProfileEditValue] = [:]
  public let id: UUID
  public var name: String
  public let steamAppID: String
  public let canonicalURL: String
  public let favorite: Bool
  public var currentFacts: JSONObject
  public var brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
  public var analysis: JSONObject
  public let modelMetadata: JSONObject
  public let promptMetadata: JSONObject
}

public struct CreatorProfile: Identifiable, Sendable, Equatable {
  public var profileRevision: Int = 0
  public var manualOverrides: [String: ProfileEditValue] = [:]
  public let id: UUID
  public var name: String
  public let youtubeChannelID: String?
  public var platformAccountID: String = ""
  public let canonicalURL: String
  public let favorite: Bool
  public var currentFacts: JSONObject
  public var brief: JSONObject
  public let sourceStatus: JSONObject
  public let lastAnalyzedAt: Date?
  public let nextAnalysisAt: Date?
  public let contact: CreatorContact?
  public let contacts: [CreatorContact]
  public let manualNotes: String?
  public var analysis: JSONObject
  public let modelMetadata: JSONObject
  public let promptMetadata: JSONObject

  public init(
    id: UUID, name: String, youtubeChannelID: String?, platformAccountID: String? = nil,
    canonicalURL: String, favorite: Bool,
    currentFacts: JSONObject, brief: JSONObject, sourceStatus: JSONObject,
    lastAnalyzedAt: Date?, nextAnalysisAt: Date?, contact: CreatorContact?, manualNotes: String?,
    analysis: JSONObject, modelMetadata: JSONObject, promptMetadata: JSONObject,
    contacts: [CreatorContact]? = nil
  ) {
    self.id = id
    self.name = name
    self.youtubeChannelID = youtubeChannelID
    self.platformAccountID = platformAccountID ?? youtubeChannelID ?? ""
    self.canonicalURL = canonicalURL
    self.favorite = favorite
    self.currentFacts = currentFacts
    self.brief = brief
    self.sourceStatus = sourceStatus
    self.lastAnalyzedAt = lastAnalyzedAt
    self.nextAnalysisAt = nextAnalysisAt
    self.contact = contact
    self.contacts = contacts ?? contact.map { [$0] } ?? []
    self.manualNotes = manualNotes
    self.analysis = analysis
    self.modelMetadata = modelMetadata
    self.promptMetadata = promptMetadata
  }

  public var contactAvailability: ContactAvailability {
    contacts.first?.availability ?? .unavailable
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
