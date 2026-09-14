import Foundation

@testable import FindMeGamerCore

// Existing service doubles concern unrelated workflows. Editor tests use actual transport or explicit closures.
extension APIService {
  func profileEdit(type: ProfileType, id: UUID) async throws -> ProfileEditDocument {
    throw APIError.invalidResponse
  }
  func saveProfileEdit(type: ProfileType, id: UUID, patch: ProfileEditPatch) async throws
    -> ProfileEditDocument
  { throw APIError.invalidResponse }
}
