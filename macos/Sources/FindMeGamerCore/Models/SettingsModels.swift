import Foundation

public enum SMTPEncryption: String, Sendable, Equatable, Hashable, CaseIterable {
  case tls
  case startTLS
  case none

  public var displayName: String {
    switch self {
    case .tls: "TLS"
    case .startTLS: "STARTTLS"
    case .none: "None"
    }
  }
}

public struct SMTPSettingsStatus: Sendable, Equatable, Hashable {
  public let configured: Bool
  public let host: String?
  public let port: Int?
  public let encryption: SMTPEncryption?
  public let username: String?
  public let fromName: String?
  public let replyTo: String?
  public let emailsPerMinute: Int
  public let lastTestStatus: ConnectionTestStatus
  public let lastTestedAt: Date?
}

public struct SMTPSettingsDraft: Sendable, Equatable, Hashable {
  public let host: String
  public let port: Int?
  public let encryption: SMTPEncryption?
  public let username: String
  public let password: String?
  public let fromName: String
  public let replyTo: String
  public let emailsPerMinute: Int?

  public init(
    host: String,
    port: Int? = nil,
    encryption: SMTPEncryption? = nil,
    username: String,
    password: String? = nil,
    fromName: String,
    replyTo: String,
    emailsPerMinute: Int? = nil
  ) {
    self.host = host
    self.port = port
    self.encryption = encryption
    self.username = username
    self.password = password
    self.fromName = fromName
    self.replyTo = replyTo
    self.emailsPerMinute = emailsPerMinute
  }
}

public enum ConnectionService: String, Sendable, Equatable, Hashable, CaseIterable {
  case deepSeek = "deepseek"
  case steam
  case youtube
  case s3
  public var displayName: String {
    switch self {
    case .deepSeek: "DeepSeek"
    case .steam: "Steam"
    case .youtube: "YouTube"
    case .s3: "S3"
    }
  }
}

public struct ConnectionStatus: Sendable, Equatable, Hashable {
  public let service: ConnectionService
  public let configured: Bool
  public let lastTestStatus: ConnectionTestStatus
  public let lastTestedAt: Date?
}

public struct ReanalysisDraft: Sendable, Equatable, Hashable {
  public let gameIntervalDays: Int
  public let creatorIntervalDays: Int

  public init(gameIntervalDays: Int, creatorIntervalDays: Int) {
    self.gameIntervalDays = gameIntervalDays
    self.creatorIntervalDays = creatorIntervalDays
  }
}

public struct SharedSettings: Sendable, Equatable, Hashable {
  public let gameIntervalDays: Int
  public let creatorIntervalDays: Int
}
