import Foundation
import Observation

@MainActor @Observable
public final class ProfileEditorState {
  public private(set) var document: ProfileEditDocument
  public private(set) var changes: [String: ProfileEditValue] = [:]
  public private(set) var resetFields: Set<String> = []
  public private(set) var isBusy = false
  public private(set) var needsReconciliation = false
  public private(set) var didSave = false
  public private(set) var message: String?
  private var outcomeUnknown = false

  public init(document: ProfileEditDocument) { self.document = document }
  public var isDirty: Bool { !changes.isEmpty || !resetFields.isEmpty }
  public var patch: ProfileEditPatch {
    .init(expectedRevision: document.revision, changes: changes, resetFields: resetFields.sorted())
  }
  public var canSave: Bool {
    isDirty && !isBusy && !needsReconciliation
      && document.fields.allSatisfy {
        !$0.required || changes[$0.key] == nil
          || !value(for: $0.key).text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      }
  }
  public func value(for key: String) -> ProfileEditValue {
    guard let field = document.fields.first(where: { $0.key == key }) else { return .text("") }
    if resetFields.contains(key) {
      return field.sourceValue ?? (field.kind == "list" ? .list([]) : .text(""))
    }
    return changes[key] ?? field.value
  }
  public func isManual(_ field: ProfileEditField) -> Bool {
    !resetFields.contains(field.key) && (changes[field.key] != nil || field.isOverridden)
  }
  public func set(_ value: ProfileEditValue, for key: String) {
    guard !isBusy, !needsReconciliation, let field = document.fields.first(where: { $0.key == key })
    else { return }
    resetFields.remove(key)
    changes[key] = value == field.value ? nil : value
    didSave = false
  }
  public func reset(_ key: String) {
    guard !isBusy, !needsReconciliation, let field = document.fields.first(where: { $0.key == key })
    else { return }
    changes[key] = nil
    if field.isOverridden { resetFields.insert(key) }
    didSave = false
  }
  public func cancel() {
    guard !isBusy else { return }
    changes = [:]
    resetFields = []
    message = nil
  }
  public func save(using action: (ProfileEditPatch) async throws -> ProfileEditDocument) async {
    guard canSave else { return }
    isBusy = true
    message = nil
    defer { isBusy = false }
    do {
      let saved = try await action(patch)
      try validateIdentity(saved)
      document = saved
      changes = [:]
      resetFields = []
      didSave = true
      message = "Profile saved."
    } catch let error as APIError where error.code == "profile_revision_conflict" {
      needsReconciliation = true
      message =
        "This profile changed. Read the latest profile and review your draft before saving again."
    } catch let error as APIError
      where error.code == "profile_edit_invalid" || error.code == "missing_workspace_key"
      || error.code == "http_401" || error.code == "http_403"
    {
      message = error.message
    } catch {
      outcomeUnknown = true
      needsReconciliation = true
      message =
        "Save could not be confirmed. Read the current profile to check whether it was saved. Your draft is retained."
    }
  }
  public func reconcile(using read: () async throws -> ProfileEditDocument) async {
    guard needsReconciliation, !isBusy else { return }
    isBusy = true
    defer { isBusy = false }
    do {
      let fresh = try await read()
      try validateIdentity(fresh)
      let committed =
        changes.allSatisfy { key, value in
          fresh.fields.contains { $0.key == key && $0.value == value && $0.isOverridden }
        }
        && resetFields.allSatisfy { key in
          fresh.fields.contains { $0.key == key && !$0.isOverridden }
        }
      document = fresh
      needsReconciliation = false
      if outcomeUnknown && committed {
        changes = [:]
        resetFields = []
        didSave = true
        message = "Profile saved. Confirmed by reading the current profile."
      } else {
        message =
          "Latest profile loaded. Your draft is retained; review it against the current values before saving."
      }
      outcomeUnknown = false
    } catch {
      message =
        "Could not read the current profile. Your draft is retained. Retry the read before saving."
    }
  }
  private func validateIdentity(_ value: ProfileEditDocument) throws {
    guard value.profileID == document.profileID, value.profileType == document.profileType else {
      throw APIError.invalidResponse
    }
  }
}
