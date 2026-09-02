import Foundation
import HTTPTypes
import OpenAPIRuntime

struct WorkspaceAuthMiddleware: ClientMiddleware {
  typealias KeyProvider = @Sendable () async throws -> String?
  typealias CorrelationIDProvider = @Sendable () -> String

  private let keyProvider: KeyProvider
  private let correlationIDProvider: CorrelationIDProvider

  init(
    keyProvider: @escaping KeyProvider,
    correlationIDProvider: @escaping CorrelationIDProvider = { UUID().uuidString }
  ) {
    self.keyProvider = keyProvider
    self.correlationIDProvider = correlationIDProvider
  }

  func intercept(
    _ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String,
    next: @Sendable (HTTPRequest, HTTPBody?, URL) async throws -> (HTTPResponse, HTTPBody?)
  ) async throws -> (HTTPResponse, HTTPBody?) {
    guard let key = try await keyProvider()?.trimmingCharacters(in: .whitespacesAndNewlines),
      !key.isEmpty
    else {
      throw APIError(
        code: "missing_workspace_key",
        message: "A workspace key is required to connect.", retryable: false)
    }

    var authenticated = request
    authenticated.headerFields[.authorization] = "Bearer \(key)"
    authenticated.headerFields[HTTPField.Name("X-Correlation-ID")!] = correlationIDProvider()
    let (response, responseBody) = try await next(authenticated, body, baseURL)
    guard !(200..<300).contains(response.status.code) else { return (response, responseBody) }

    let data: Data
    if let responseBody {
      data = (try? await Data(collecting: responseBody, upTo: 1_000_000)) ?? Data()
    } else {
      data = Data()
    }
    throw Self.apiError(response: response, data: data)
  }

  private static func apiError(response: HTTPResponse, data: Data) -> APIError {
    struct Envelope: Decodable {
      struct Detail: Decodable {
        let code: String
        let message: String
        let retryable: Bool
        let correlationID: String?

        enum CodingKeys: String, CodingKey {
          case code, message, retryable
          case correlationID = "correlation_id"
        }
      }
      let error: Detail
    }

    let responseCorrelationID = response.headerFields[HTTPField.Name("X-Correlation-ID")!]
    if let envelope = try? JSONDecoder().decode(Envelope.self, from: data) {
      return APIError(
        code: envelope.error.code, message: envelope.error.message,
        retryable: envelope.error.retryable,
        correlationID: responseCorrelationID ?? envelope.error.correlationID)
    }
    return APIError(
      code: "http_\(response.status.code)",
      message: "The server could not complete the request.",
      retryable: response.status.code == 429 || response.status.code >= 500,
      correlationID: responseCorrelationID)
  }
}
