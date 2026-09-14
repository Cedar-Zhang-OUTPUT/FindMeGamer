import Foundation
import HTTPTypes
import OpenAPIRuntime
import Testing

@testable import FindMeGamerCore

@Suite struct ProfileEditingServiceTests {
  @Test func demoEditsBothTypesAndResetRestoresSource() async throws {
    let api = DemoAPIService()
    for type in ProfileType.allCases {
      let card = try #require(
        try await api.listProfiles(
          type: type, query: "", onlyCollection: false, cursor: nil, limit: 1
        ).items.first)
      let original = try await api.profileEdit(type: type, id: card.id)
      let sourceProfile = try await api.profile(type: type, id: card.id)
      let key = type == .game ? "facts.name" : "facts.title"
      let saved = try await api.saveProfileEdit(
        type: type, id: card.id,
        patch: .init(
          expectedRevision: original.revision, changes: [key: .text("Human title")], resetFields: []
        ))
      #expect(saved.revision == original.revision + 1)
      _ = try await api.setFavorite(type: type, id: card.id, favorite: true)
      switch try await api.profile(type: type, id: card.id) {
      case .game(let game):
        #expect(game.name == "Human title")
        #expect(game.manualOverrides[key] == .text("Human title"))
      case .creator(let creator):
        #expect(creator.name == "Human title")
        #expect(creator.manualOverrides[key] == .text("Human title"))
      }
      let reset = try await api.saveProfileEdit(
        type: type, id: card.id,
        patch: .init(expectedRevision: saved.revision, changes: [:], resetFields: [key]))
      #expect(reset.fields.first?.value == original.fields.first?.value)
      #expect(reset.fields.first?.isOverridden == false)
      switch (sourceProfile, try await api.profile(type: type, id: card.id)) {
      case (.game(let source), .game(let current)): #expect(current.analysis == source.analysis)
      case (.creator(let source), .creator(let current)):
        #expect(current.analysis == source.analysis)
      default: Issue.record("Wrong profile type")
      }
    }
  }
  @Test func typedEditorUsesAuthenticatedSingularPathsAndRealJSON() async throws {
    let transport = EditTransport()
    let service = OpenAPIService(
      baseURL: URL(string: "https://example.test")!, transport: transport,
      keyProvider: { "editor-key" }, correlationIDProvider: { "editor-correlation" })
    let id = UUID(uuidString: "10000000-0000-4000-8000-000000000001")!
    let document = try await service.profileEdit(type: .game, id: id)
    #expect(document.fields[0].sourceValue == nil)
    #expect(document.fields[1].sourceValue == .list(["Original"]))
    _ = try await service.saveProfileEdit(
      type: .game, id: id,
      patch: .init(
        expectedRevision: 2, changes: ["facts.name": .text("Human"), "analysis.themes": .list([])],
        resetFields: []))
    let requests = await transport.requests
    #expect(requests.count == 2)
    #expect(requests.allSatisfy { $0.headerFields[.authorization] == "Bearer editor-key" })
    #expect(
      requests.allSatisfy {
        $0.path?.lowercased() == "/api/v1/profiles/game/10000000-0000-4000-8000-000000000001/edit"
      })
    let body = try JSONSerialization.jsonObject(with: await transport.patchBody) as! [String: Any]
    #expect(body["expected_revision"] as? Int == 2)
    let changes = body["changes"] as! [String: Any]
    #expect(changes["facts.name"] as? String == "Human")
    #expect(changes["analysis.themes"] as? [String] == [])
  }
  @Test func conflictSurvivesGeneratedTransport() async throws {
    let transport = EditTransport(conflict: true)
    let service = OpenAPIService(
      baseURL: URL(string: "https://example.test")!, transport: transport,
      keyProvider: { "key" }, correlationIDProvider: { "cid" })
    do {
      _ = try await service.saveProfileEdit(
        type: .creator, id: UUID(),
        patch: .init(expectedRevision: 0, changes: [:], resetFields: []))
      Issue.record("Expected conflict")
    } catch let error as APIError { #expect(error.code == "profile_revision_conflict") }
  }
}

private actor EditTransport: ClientTransport {
  var requests: [HTTPRequest] = []
  var patchBody = Data()
  let conflict: Bool
  init(conflict: Bool = false) { self.conflict = conflict }
  func send(_ request: HTTPRequest, body: HTTPBody?, baseURL: URL, operationID: String) async throws
    -> (HTTPResponse, HTTPBody?)
  {
    requests.append(request)
    if let body { patchBody = try await Data(collecting: body, upTo: 100_000) }
    let json =
      conflict
      ? #"{"error":{"code":"profile_revision_conflict","message":"Changed","retryable":false}}"#
      : #"{"profile_type":"game","profile_id":"10000000-0000-4000-8000-000000000001","revision":2,"fields":[{"key":"facts.name","section":"facts","label":"Name","kind":"text","required":true,"value":"Human","source_value":null,"is_overridden":true},{"key":"analysis.themes","section":"analysis","label":"Themes","kind":"list","required":false,"value":[],"source_value":["Original"],"is_overridden":true}]}"#
    return (
      HTTPResponse(
        status: conflict ? .conflict : .ok, headerFields: [.contentType: "application/json"]),
      HTTPBody(json)
    )
  }
}
