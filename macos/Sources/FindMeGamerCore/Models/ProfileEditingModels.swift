import Foundation

public enum ProfileEditValue: Sendable, Equatable, Codable {
  case text(String)
  case list([String])

  public init(from decoder: any Decoder) throws {
    let container = try decoder.singleValueContainer()
    if let text = try? container.decode(String.self) {
      self = .text(text)
    } else {
      self = .list(try container.decode([String].self))
    }
  }
  public func encode(to encoder: any Encoder) throws {
    var container = encoder.singleValueContainer()
    switch self {
    case .text(let value): try container.encode(value)
    case .list(let value): try container.encode(value)
    }
  }
  public var text: String {
    switch self {
    case .text(let text): text
    case .list(let items): items.joined(separator: "\n")
    }
  }
}

public struct ProfileEditField: Identifiable, Sendable, Equatable, Codable {
  public var id: String { key }
  public let key: String
  public let section: String
  public let label: String
  public let kind: String
  public let required: Bool
  public var value: ProfileEditValue
  public let sourceValue: ProfileEditValue?
  public var isOverridden: Bool
  enum CodingKeys: String, CodingKey {
    case key, section, label, kind, required, value
    case sourceValue = "source_value"
    case isOverridden = "is_overridden"
  }
}

public struct ProfileEditDocument: Sendable, Equatable, Codable {
  public let profileType: ProfileType
  public let profileID: UUID
  public var revision: Int
  public var fields: [ProfileEditField]
  enum CodingKeys: String, CodingKey {
    case profileType = "profile_type"
    case profileID = "profile_id"
    case revision, fields
  }
}

public struct ProfileEditPatch: Sendable, Equatable, Codable {
  public let expectedRevision: Int
  public let changes: [String: ProfileEditValue]
  public let resetFields: [String]
  enum CodingKeys: String, CodingKey {
    case expectedRevision = "expected_revision"
    case changes
    case resetFields = "reset_fields"
  }
}
