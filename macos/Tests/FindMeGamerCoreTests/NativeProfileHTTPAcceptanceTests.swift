import Foundation
import Testing

@testable import FindMeGamerCore

/// Opt in only with the dedicated local fixture server; never accesses Keychain.
@MainActor @Suite struct NativeProfileHTTPAcceptanceTests {
  @Test(.enabled(if: ProcessInfo.processInfo.environment["FMG_NATIVE_HTTP_ACCEPTANCE"] == "1"))
  func realHTTPProfileDraftSaveConflictResetAndMatchRevisions() async throws {
    let api = OpenAPIService(
      baseURL: URL(string: "http://127.0.0.1:18764")!,
      keyProvider: { "test-workspace-access-key" })
    _ = try await api.validateSession()
    let gameID = UUID(uuidString: "a4000000-0000-4000-8000-000000000001")!
    let creatorID = UUID(uuidString: "a4000000-0000-4000-8000-000000000002")!
    let oldMatch = try await api.createMatch(gameID: gameID, idempotencyKey: UUID().uuidString)
    for (type, id, field) in [
      (ProfileType.game, gameID, "facts.name"), (.creator, creatorID, "facts.title")
    ] {
      let before = try await api.profileEdit(type: type, id: id)
      let state = ProfileEditorState(document: before)
      state.set(.text("Native HTTP accepted \(type.rawValue)"), for: field)
      // Draft keystrokes and Cancel do not change the real server revision/value.
      #expect(try await api.profileEdit(type: type, id: id) == before)
      state.cancel()
      #expect(try await api.profileEdit(type: type, id: id) == before)
      state.set(.text("Native HTTP accepted \(type.rawValue)"), for: field)
      await state.save { try await api.saveProfileEdit(type: type, id: id, patch: $0) }
      #expect(state.didSave)
      let reopened = try await api.profileEdit(type: type, id: id)
      #expect(reopened.revision == before.revision + 1)
      #expect(reopened.fields.first { $0.key == field }?.value == .text("Native HTTP accepted \(type.rawValue)"))
      do {
        _ = try await api.saveProfileEdit(type: type, id: id, patch: .init(
          expectedRevision: before.revision, changes: [field: .text("Stale overwrite")], resetFields: []))
        Issue.record("A stale editor must not overwrite the saved profile")
      } catch let error as APIError {
        #expect(error.code == "profile_revision_conflict")
      }
      #expect(try await api.profileEdit(type: type, id: id) == reopened)
      let reset = try await api.saveProfileEdit(type: type, id: id, patch: .init(
        expectedRevision: reopened.revision, changes: [:], resetFields: [field]))
      let restored = try #require(reset.fields.first { $0.key == field })
      #expect(!restored.isOverridden)
      #expect(restored.value == restored.sourceValue)
      #expect(try await api.profileEdit(type: type, id: id) == reset)
    }
    let contact = try await api.updateCreatorManual(
      id: creatorID, email: "native-http@example.com", notes: "Local HTTP fixture")
    #expect(contact.contact?.email == "native-http@example.com")
    let detail = try await api.match(id: oldMatch.id)
    #expect(detail.profileRevisions.count == 2)
    #expect(detail.profileRevisions.allSatisfy { $0.currentRevision == ($0.snapshotRevision ?? -100) + 2 })
    let newMatch = try await api.createMatch(gameID: gameID, idempotencyKey: UUID().uuidString)
    let fresh = try await api.match(id: newMatch.id)
    #expect(fresh.profileRevisions.allSatisfy { $0.currentRevision == $0.snapshotRevision })
  }
}
