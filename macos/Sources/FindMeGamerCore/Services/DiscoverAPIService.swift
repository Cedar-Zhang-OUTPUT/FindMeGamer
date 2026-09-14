import FindMeGamerAPI
import Foundation

public protocol DiscoverAPIService: Sendable {
  func discoverCapabilities() async throws -> [DiscoverCapability]
  func discoverGames(cursor: String?) async throws -> DiscoverGamePage
  func resolveDiscoverGame(url: String) async throws -> DiscoverGame
  func discoverHistory(cursor: String?) async throws -> DiscoverPage
  func discover(id: UUID) async throws -> DiscoverRecord
  func retryDiscover(id: UUID) async throws -> DiscoverRecord
  func createDiscover(game: DiscoverGame, conditions: DiscoverConditions, idempotencyKey: String)
    async throws -> DiscoverRecord
  func discoverBatches(id: UUID) async throws -> [DiscoverBatch]
  func createDiscoverBatch(
    id: UUID, candidateIDs: [UUID], mode: DiscoverAnalysisMode, idempotencyKey: String
  ) async throws -> DiscoverBatch
}

extension APIService {
  public func discoverGames(cursor: String?) async throws -> DiscoverGamePage {
    let page = try await listProfiles(
      type: .game, query: "", onlyCollection: false, cursor: cursor, limit: 100)
    return .init(
      items: page.items.compactMap {
        guard case .game(let game) = $0 else { return nil }
        return DiscoverGame(id: game.id, name: game.name, url: game.canonicalURL)
      }, nextCursor: page.nextCursor)
  }
}

extension OpenAPIService {
  public func retryDiscover(id: UUID) async throws -> DiscoverRecord {
    let value = try await perform {
      try await client.retryDiscover(.init(path: .init(discover_id: id.uuidString)))
    }.accepted.body.json
    return try mapDiscover(value)
  }
  public func discoverCapabilities() async throws -> [DiscoverCapability] {
    let value = try await perform { try await client.getDiscoverCapabilities() }.ok.body.json
    return value.platforms.map {
      .init(platform: $0.platform.rawValue, available: $0.available, reason: $0.reason)
    }
  }
  public func resolveDiscoverGame(url: String) async throws -> DiscoverGame {
    let value = try await perform {
      try await client.resolveDiscoverGame(.init(body: .json(.init(steam_url: url))))
    }.ok.body.json
    return .init(
      id: try value.game_id.map(discoverUUID), name: value.name, url: value.canonical_url)
  }
  public func discoverHistory(cursor: String?) async throws -> DiscoverPage {
    let value = try await perform {
      try await client.listDiscover(.init(query: .init(cursor: cursor)))
    }.ok.body.json
    return try .init(
      items: value.items.map {
        .init(
          id: try discoverUUID($0.id), gameName: $0.game_name,
          status: $0.status.rawValue, candidateCount: $0.candidate_count, createdAt: $0.created_at)
      }, nextCursor: value.next_cursor)
  }
  public func discover(id: UUID) async throws -> DiscoverRecord {
    let value = try await perform {
      try await client.getDiscover(.init(path: .init(discover_id: id.uuidString)))
    }.ok.body.json
    return try mapDiscover(value)
  }
  public func createDiscover(
    game: DiscoverGame, conditions: DiscoverConditions, idempotencyKey: String
  ) async throws -> DiscoverRecord {
    let request = Components.Schemas.DiscoverCreate(
      conditions: .init(
        content_languages: conditions.language.split(separator: ",").map {
          $0.trimmingCharacters(in: .whitespaces)
        }.filter { !$0.isEmpty },
        keywords: conditions.keywords, max_followers: Int(conditions.maximumFollowers),
        min_followers: Int(conditions.minimumFollowers),
        platforms: conditions.platforms.sorted().compactMap { .init(rawValue: $0) }),
      game_id: game.id?.uuidString, steam_url: game.id == nil ? game.url : nil)
    let value = try await perform {
      try await client.createDiscover(
        .init(headers: .init(Idempotency_hyphen_Key: idempotencyKey), body: .json(request)))
    }.accepted.body.json
    return try mapDiscover(value)
  }
  public func discoverBatches(id: UUID) async throws -> [DiscoverBatch] {
    let value = try await perform {
      try await client.listDiscoverAnalysisBatches(.init(path: .init(discover_id: id.uuidString)))
    }.ok.body.json
    return try value.items.map(mapDiscoverBatch)
  }
  public func createDiscoverBatch(
    id: UUID, candidateIDs: [UUID], mode: DiscoverAnalysisMode, idempotencyKey: String
  ) async throws -> DiscoverBatch {
    let request = Components.Schemas.DiscoverBatchCreate(
      candidate_ids: candidateIDs.map(\.uuidString), mode: .init(rawValue: mode.rawValue)!)
    let value = try await perform {
      try await client.createDiscoverAnalysisBatch(
        .init(
          path: .init(discover_id: id.uuidString),
          headers: .init(Idempotency_hyphen_Key: idempotencyKey), body: .json(request)))
    }.accepted.body.json
    return try mapDiscoverBatch(value)
  }
}

private func discoverUUID(_ value: String) throws -> UUID {
  guard let id = UUID(uuidString: value) else { throw APIError.invalidResponse }
  return id
}
private func mapDiscover(_ value: Components.Schemas.DiscoverDetail) throws -> DiscoverRecord {
  try .init(
    id: discoverUUID(value.id), gameID: value.game_id.map(discoverUUID), gameName: value.game_name,
    status: value.status.rawValue, stage: value.stage?.rawValue,
    candidates: value.candidates.map {
      .init(
        id: try discoverUUID($0.id), platform: $0.platform.rawValue,
        accountID: $0.platform_account_id, name: $0.display_name, url: $0.canonical_url,
        inLibrary: $0.in_library ?? false)
    },
    issues: value.issues.map(\.message), createdAt: value.created_at)
}
private func mapDiscoverBatch(_ value: Components.Schemas.DiscoverBatchDetail) throws
  -> DiscoverBatch
{
  try .init(
    id: discoverUUID(value.id), discoverID: discoverUUID(value.discover_id),
    mode: .init(rawValue: value.mode.rawValue)!,
    status: value.status.rawValue,
    items: value.items.map {
      .init(
        candidateID: try discoverUUID($0.candidate_id),
        status: $0.status.rawValue, reused: $0.reused ?? false, error: $0.error?.value1.message,
        analysisJobID: try $0.analysis_job_id.map(discoverUUID))
    },
    matchID: value.match_task_id.map(discoverUUID), error: value.error?.value1.message)
}
