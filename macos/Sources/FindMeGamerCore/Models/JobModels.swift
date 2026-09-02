import Foundation

public enum AnalysisMode: String, Sendable, Equatable, Hashable {
  case create
  case reanalyze
  public var displayName: String { self == .create ? "Analyze" : "Reanalyze" }
}

public enum JobStatus: String, Sendable, Equatable, Hashable {
  case queued, running, succeeded, failed, superseded
  public var displayName: String { rawValue.capitalized }
}

public enum AnalysisStage: String, Sendable, Equatable, Hashable {
  case fetchingData, analyzing, finalizing
  public var displayName: String {
    switch self {
    case .fetchingData: "Fetching data"
    default: rawValue.capitalized
    }
  }
}

public struct JobFailure: Sendable, Equatable, Hashable {
  public let code: String
  public let message: String
}

public struct AnalysisRequest: Sendable, Equatable, Hashable {
  public let url: String
  public let profileType: ProfileType
  public let mode: AnalysisMode?

  public init(url: String, profileType: ProfileType, mode: AnalysisMode? = nil) {
    self.url = url
    self.profileType = profileType
    self.mode = mode
  }
}

public struct AnalysisJob: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let profileType: ProfileType
  public let canonicalTargetID: String
  public let canonicalURL: String
  public let mode: AnalysisMode
  public let status: JobStatus
  public let stage: AnalysisStage?
  public let completedUnits: Int
  public let totalUnits: Int
  public let retryable: Bool
  public let correlationID: String?
  public let profileID: UUID?
  public let createdAt: Date
  public let updatedAt: Date
  public let startedAt: Date?
  public let completedAt: Date?
  public let failure: JobFailure?
}

public struct ExistingProfile: Sendable, Equatable, Hashable {
  public let profileID: UUID
  public let profileType: ProfileType
  public let canonicalTargetID: String
  public let canonicalURL: String
}

public enum AnalysisSubmission: Sendable, Equatable, Hashable {
  case job(AnalysisJob)
  case existingProfile(ExistingProfile)
}

public enum JobChange: Sendable, Equatable, Hashable {
  case analysis(AnalysisJob)
  case match(ChangedMatchJob)
}

public struct ChangedMatchJob: Identifiable, Sendable, Equatable, Hashable {
  public let id: UUID
  public let gameID: UUID
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

public struct JobChangePage: Sendable, Equatable, Hashable {
  public let items: [JobChange]
  public let cursor: String
  public let hasMore: Bool
  public let affectedProfileIDs: [UUID]
}
