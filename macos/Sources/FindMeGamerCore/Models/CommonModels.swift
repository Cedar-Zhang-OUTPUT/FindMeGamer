import Foundation

public enum JSONValue: Sendable, Equatable {
  case string(String)
  case integer(Int)
  case number(Double)
  case boolean(Bool)
  case object(JSONObject)
  case array([JSONValue])
  case null
}

public typealias JSONObject = [String: JSONValue]

public struct APIError: Error, Sendable, Equatable, CustomStringConvertible {
  public let code: String
  public let message: String
  public let retryable: Bool
  public let correlationID: String?

  public init(code: String, message: String, retryable: Bool, correlationID: String? = nil) {
    self.code = code
    self.message = message
    self.retryable = retryable
    self.correlationID = correlationID
  }

  public var description: String {
    correlationID.map { "\(message) (Reference: \($0))" } ?? message
  }

  static var invalidResponse: APIError {
    APIError(
      code: "invalid_response",
      message: "The server returned an unexpected response.",
      retryable: false
    )
  }
}

public enum ConnectionTestStatus: String, Sendable, Equatable, Hashable {
  case success
  case failed
  case notTested

  public var displayName: String {
    switch self {
    case .success: "Connected"
    case .failed: "Failed"
    case .notTested: "Not tested"
    }
  }
}

public struct WorkspaceSession: Sendable, Equatable {
  public let workspaceName: String
  public let apiVersion: String
  public let serviceConnections: [String: Bool]

  public init(workspaceName: String, apiVersion: String, serviceConnections: [String: Bool]) {
    self.workspaceName = workspaceName
    self.apiVersion = apiVersion
    self.serviceConnections = serviceConnections
  }
}

public struct ConnectionTestResult: Sendable, Equatable, Hashable {
  public let succeeded: Bool
  public let status: ConnectionTestStatus
  public let testedAt: Date?

  public init(succeeded: Bool, status: ConnectionTestStatus, testedAt: Date?) {
    self.succeeded = succeeded
    self.status = status
    self.testedAt = testedAt
  }
}
