import Foundation
import Testing

@testable import FindMeGamerCore

@MainActor @Suite struct ProfileEditorStateTests {
  func document() -> ProfileEditDocument {
    .init(
      profileType: .game, profileID: UUID(), revision: 3,
      fields: [
        .init(
          key: "facts.name", section: "facts", label: "Name", kind: "text", required: true,
          value: .text("Manual"), sourceValue: .text("Source"), isOverridden: true),
        .init(
          key: "analysis.themes", section: "analysis", label: "Themes", kind: "list",
          required: false,
          value: .list(["Cozy"]), sourceValue: nil, isOverridden: false),
      ])
  }

  @Test func localDraftResetAndCancelNeverWrite() {
    let original = document()
    let state = ProfileEditorState(document: original)
    state.set(.list(["Adventure", "Comedy"]), for: "analysis.themes")
    state.reset("facts.name")
    #expect(state.patch.changes == ["analysis.themes": .list(["Adventure", "Comedy"])])
    #expect(state.patch.resetFields == ["facts.name"])
    #expect(state.document == original)
    #expect(state.isDirty)
    state.cancel()
    #expect(!state.isDirty)
    #expect(state.document == original)
  }

  @Test func conflictPreservesDraftAndRequiresReadBeforeExplicitRetry() async {
    let state = ProfileEditorState(document: document())
    state.set(.text("My title"), for: "facts.name")
    var saves = 0
    await state.save { _ in
      saves += 1
      throw APIError(code: "profile_revision_conflict", message: "Conflict", retryable: false)
    }
    #expect(saves == 1)
    #expect(state.needsReconciliation)
    #expect(state.value(for: "facts.name") == .text("My title"))
    await state.save { _ in
      saves += 1
      return state.document
    }
    #expect(saves == 1)
    var fresh = state.document
    fresh.revision = 4
    await state.reconcile { fresh }
    #expect(state.patch.expectedRevision == 4)
    #expect(state.value(for: "facts.name") == .text("My title"))
    #expect(!state.needsReconciliation)
    #expect(state.isDirty)
  }

  @Test func lostResponseReadRecognizesCommittedOverrideWithoutRepeatingPatch() async {
    let state = ProfileEditorState(document: document())
    state.set(.text("Saved title"), for: "facts.name")
    var saves = 0
    await state.save { _ in
      saves += 1
      throw URLError(.networkConnectionLost)
    }
    #expect(state.needsReconciliation)
    var fresh = state.document
    fresh.revision = 4
    fresh.fields[0].value = .text("Saved title")
    await state.reconcile { fresh }
    #expect(saves == 1)
    #expect(!state.isDirty)
    #expect(state.didSave)
  }

  @Test func unknownOutcomeFailedReadKeepsSaveDisabledAndInput() async {
    let state = ProfileEditorState(document: document())
    state.set(.text("Pending"), for: "facts.name")
    await state.save { _ in throw URLError(.timedOut) }
    await state.reconcile { throw URLError(.notConnectedToInternet) }
    #expect(state.needsReconciliation)
    #expect(state.value(for: "facts.name") == .text("Pending"))
  }

  @Test func unavailableRequiredSourceDoesNotBlockUnrelatedEdits() {
    var source = document()
    source.fields[0].value = .text("")
    let state = ProfileEditorState(document: source)
    state.set(.list(["Manual theme"]), for: "analysis.themes")
    #expect(state.canSave)
    state.set(.text("   "), for: "facts.name")
    #expect(!state.canSave)
  }
}
