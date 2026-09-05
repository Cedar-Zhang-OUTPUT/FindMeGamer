import Foundation

public enum MatchStage: String, Sendable, Equatable, Hashable {
  case screening, pairwise, ranking
  public var displayName: String { rawValue.capitalized }
}

public enum MatchResultState: String, Sendable, Equatable, Hashable {
  case pending, available, noSuitableCreators
  public var displayName: String {
    switch self {
    case .pending: "Pending"
    case .available: "Available"
    case .noSuitableCreators: "No suitable creators"
    }
  }
}

public enum MatchGroup: String, Sendable, Equatable, Hashable {
  case recommended, other
  public var displayName: String { rawValue.capitalized }
}

public enum MatchLabel: String, Sendable, Equatable, Hashable {
  case strong, good, limited
  public var displayName: String {
    switch self {
    case .strong: "Strong Match"
    case .good: "Good Match"
    case .limited: "Limited Match"
    }
  }
}

public enum SendState: String, Sendable, Equatable, Hashable {
  case notSent, queued, sending, sent, failed, superseded
  public var displayName: String { self == .notSent ? "Not sent" : rawValue.capitalized }
}

public enum ResponseState: String, Sendable, Equatable, Hashable {
  case pending, accepted, declined, noResponse
  public var displayName: String {
    switch self {
    case .pending: "Pending"
    case .accepted: "Accepted"
    case .declined: "Declined"
    case .noResponse: "No response"
    }
  }
}

public struct MatchGameHeader: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let name: String
  public let steamAppID: String
  public let canonicalURL: String
  public let coverURL: String?
}

public struct MatchTask: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let game: MatchGameHeader
  public let status: JobStatus
  public let stage: MatchStage
  public let completedUnits: Int
  public let totalUnits: Int
  public let resultCount: Int
  public let retryable: Bool
  public let failure: JobFailure?
  public let correlationID: String?
  public let supersedesID: UUID?
  public let createdAt: Date
  public let updatedAt: Date
  public let startedAt: Date?
  public let completedAt: Date?
}

public struct MatchTaskPage: Sendable, Equatable, Hashable {
  public let items: [MatchTask]
  public let cursor: String?
  public let hasMore: Bool
}

public struct MatchCreatorContact: Sendable, Equatable, Hashable {
  public let email: String
  public let source: String
  public let sourceURL: String?
  public let validationState: String
  public let purpose: String?

  public init(
    email: String, source: String, sourceURL: String?, validationState: String,
    purpose: String? = nil
  ) {
    self.email = email
    self.source = source
    self.sourceURL = sourceURL
    self.validationState = validationState
    self.purpose = purpose
  }
}

public struct MatchCreatorCard: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let name: String
  public let youtubeChannelID: String
  public let canonicalURL: String
  public let favorite: Bool
  public let contactAvailable: Bool
  public let contact: MatchCreatorContact?
  public let contacts: [MatchCreatorContact]
  public let avatarURL: String?
  public let performanceSummary: String?
  public let subscriberCount: Int?
  public let recentAverageViews: Int?
  public let recentMedianViews: Int?

  public init(
    id: UUID, name: String, youtubeChannelID: String, canonicalURL: String, favorite: Bool,
    contactAvailable: Bool, contact: MatchCreatorContact?, avatarURL: String?,
    performanceSummary: String?, subscriberCount: Int?, recentAverageViews: Int?,
    recentMedianViews: Int?, contacts: [MatchCreatorContact]? = nil
  ) {
    self.id = id
    self.name = name
    self.youtubeChannelID = youtubeChannelID
    self.canonicalURL = canonicalURL
    self.favorite = favorite
    self.contactAvailable = contactAvailable
    self.contact = contact
    self.contacts = contacts ?? contact.map { [$0] } ?? []
    self.avatarURL = avatarURL
    self.performanceSummary = performanceSummary
    self.subscriberCount = subscriberCount
    self.recentAverageViews = recentAverageViews
    self.recentMedianViews = recentMedianViews
  }
}

public struct MatchDimensionOutcomes: Sendable, Equatable, Hashable {
  public let contentFit: String
  public let audienceFit: String
  public let performanceFit: String
  public let promotionFit: String
  public let brandSafety: String
}

public struct MatchBriefDimension: Sendable, Equatable, Hashable {
  public let analysis: String
  public let evidence: [String]
}

public struct MatchBrief: Sendable, Equatable, Hashable {
  public let contentFit: MatchBriefDimension
  public let audienceFit: MatchBriefDimension
  public let performanceFit: MatchBriefDimension
  public let promotionFit: MatchBriefDimension
  public let brandSafety: MatchBriefDimension
  public let strengths: [String]
  public let risks: [String]
  public let evidence: [String]
  public let matchReasons: [String]
}

public struct MatchOutreach: Sendable, Equatable, Hashable {
  public let deliveryID: UUID?
  public let sendState: SendState?
  public let responseState: ResponseState?
}

public struct MatchCandidate: Identifiable, Sendable, Equatable, Hashable {
  public var id: UUID { creator.id }
  public let creator: MatchCreatorCard
  public let group: MatchGroup
  public let label: MatchLabel
  public let dimensionOutcomes: MatchDimensionOutcomes
  public let reasons: [String]
  public let brief: MatchBrief
  public let outreach: MatchOutreach
}

public struct MatchResult: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let game: MatchGameHeader
  public let status: JobStatus
  public let stage: MatchStage
  public let completedUnits: Int
  public let totalUnits: Int
  public let resultCount: Int
  public let retryable: Bool
  public let failure: JobFailure?
  public let correlationID: String?
  public let supersedesID: UUID?
  public let createdAt: Date
  public let updatedAt: Date
  public let startedAt: Date?
  public let completedAt: Date?
  public let state: MatchResultState
  public let recommendedMatches: [MatchCandidate]
  public let otherMatches: [MatchCandidate]
}
