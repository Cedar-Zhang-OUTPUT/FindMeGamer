import Foundation

@testable import FindMeGamerCore

extension APIService {
  func profileEdit(type: ProfileType, id: UUID) async throws -> ProfileEditDocument {
    throw APIError.invalidResponse
  }
  func saveProfileEdit(type: ProfileType, id: UUID, patch: ProfileEditPatch) async throws
    -> ProfileEditDocument
  { throw APIError.invalidResponse }
}
