import Foundation

@testable import FindMeGamerCore

extension APIService {
  func retryDiscover(id: UUID) async throws -> DiscoverRecord { throw APIError.invalidResponse }
  func discoverCapabilities() async throws -> [DiscoverCapability] {
    throw APIError.invalidResponse
  }
  func resolveDiscoverGame(url: String) async throws -> DiscoverGame {
    throw APIError.invalidResponse
  }
  func discoverHistory(cursor: String?) async throws -> DiscoverPage {
    throw APIError.invalidResponse
  }
  func discover(id: UUID) async throws -> DiscoverRecord { throw APIError.invalidResponse }
  func createDiscover(game: DiscoverGame, conditions: DiscoverConditions, idempotencyKey: String)
    async throws -> DiscoverRecord
  { throw APIError.invalidResponse }
  func discoverBatches(id: UUID) async throws -> [DiscoverBatch] { throw APIError.invalidResponse }
  func createDiscoverBatch(
    id: UUID, candidateIDs: [UUID], mode: DiscoverAnalysisMode, idempotencyKey: String
  ) async throws -> DiscoverBatch { throw APIError.invalidResponse }
}
