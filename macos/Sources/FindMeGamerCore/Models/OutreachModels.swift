import Foundation

public enum CampaignState: String, Sendable, Equatable, Hashable {
  case notStarted, queued, sending, completed, failed
  public var displayName: String {
    switch self {
    case .notStarted: "Not started"
    default: rawValue.capitalized
    }
  }
}

public enum SendBatchState: String, Sendable, Equatable, Hashable {
  case queued, sending, sent, partiallyFailed, failed
  public var displayName: String {
    self == .partiallyFailed ? "Partially failed" : rawValue.capitalized
  }
}

public struct CampaignGame: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let name: String
  public let steamAppID: String
  public let steamURL: String
  public let coverURL: String?
}

public struct CampaignMetrics: Sendable, Equatable, Hashable {
  public let sentCreators: Int
  public let accepted: Int
  public let declined: Int
  public let noResponse: Int
  public let failed: Int
  public let responseRate: Double
}

public struct CampaignSummary: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let matchTaskID: UUID
  public let game: CampaignGame
  public let state: CampaignState
  public let sendBatchCount: Int
  public let metrics: CampaignMetrics
  public let createdAt: Date
  public let latestActivityAt: Date
}

public struct CampaignPage: Sendable, Equatable, Hashable {
  public let items: [CampaignSummary]
  public let cursor: String?
  public let hasMore: Bool
}

public struct OutreachCreator: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let name: String
  public let youtubeChannelID: String
  public let canonicalURL: String
  public let avatarURL: String?
}

public struct SMTPFailure: Sendable, Equatable, Hashable {
  public let code: String
  public let message: String
  public let retryable: Bool
}

public struct Delivery: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let campaignID: UUID?
  public let sendBatchID: UUID?
  public let creatorID: UUID
  public let creator: OutreachCreator?
  public let recipientEmail: String
  public let sendState: SendState
  public let responseState: ResponseState
  public let resendsDeliveryID: UUID?
  public let supersededByDeliveryID: UUID?
  public let isCurrent: Bool?
  public let templateName: String?
  public let templateVersion: Int?
  public let renderedSubject: String?
  public let renderedMarkdown: String?
  public let renderedHTML: String?
  public let senderName: String?
  public let senderAddress: String?
  public let replyTo: String?
  public let acceptedLabel: String?
  public let declinedLabel: String?
  public let smtpFailure: SMTPFailure?
  public let canResend: Bool?
  public let createdAt: Date?
  public let sendingAt: Date?
  public let sentAt: Date?
  public let failedAt: Date?
  public let respondedAt: Date?
  public let supersededAt: Date?
}

public struct SendBatch: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let campaignID: UUID
  public let matchTaskID: UUID?
  public let templateID: UUID?
  public let templateName: String?
  public let templateVersion: Int?
  public let requestedCreatorIDs: [UUID]
  public let requestedAt: Date
  public let state: SendBatchState
  public let deliveries: [Delivery]
}

public struct OutreachCampaign: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let matchTaskID: UUID
  public let game: CampaignGame
  public let state: CampaignState
  public let sendBatchCount: Int
  public let metrics: CampaignMetrics
  public let createdAt: Date
  public let latestActivityAt: Date
  public let sendBatches: [SendBatch]
}

public struct OutreachTemplate: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let name: String
  public let version: Int
  public let subjectTemplate: String
  public let bodyMarkdown: String
  public let acceptedLabel: String
  public let declinedLabel: String
  public let isDefault: Bool
  public let createdAt: Date
  public let updatedAt: Date
}

public struct TemplateDraft: Sendable, Equatable, Hashable {
  public let id: UUID?
  public let name: String
  public let subjectTemplate: String
  public let bodyMarkdown: String
  public let acceptedLabel: String?
  public let declinedLabel: String?

  public init(
    id: UUID? = nil,
    name: String,
    subjectTemplate: String,
    bodyMarkdown: String,
    acceptedLabel: String? = nil,
    declinedLabel: String? = nil
  ) {
    self.id = id
    self.name = name
    self.subjectTemplate = subjectTemplate
    self.bodyMarkdown = bodyMarkdown
    self.acceptedLabel = acceptedLabel
    self.declinedLabel = declinedLabel
  }
}

public struct RenderedEmail: Sendable, Equatable, Hashable {
  public let subject: String
  public let markdown: String
  public let html: String
}

public struct RecipientPreview: Identifiable, Sendable, Equatable, Hashable {
  public var id: UUID { creatorID }
  public let creatorID: UUID
  public let creatorName: String
  public let recipientEmail: String
  public let subject: String
  public let markdown: String
  public let html: String
}

public struct SendBatchDraft: Sendable, Equatable, Hashable {
  public let matchTaskID: UUID
  public let creatorIDs: [UUID]
  public let templateID: UUID?
  public let subjectOverride: String?
  public let bodyMarkdownOverride: String?

  public init(
    matchTaskID: UUID,
    creatorIDs: [UUID],
    templateID: UUID? = nil,
    subjectOverride: String? = nil,
    bodyMarkdownOverride: String? = nil
  ) {
    self.matchTaskID = matchTaskID
    self.creatorIDs = creatorIDs
    self.templateID = templateID
    self.subjectOverride = subjectOverride
    self.bodyMarkdownOverride = bodyMarkdownOverride
  }
}
