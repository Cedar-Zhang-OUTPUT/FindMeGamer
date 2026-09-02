import CoreFoundation
import Foundation
import Security

public protocol WorkspaceKeyStore: Sendable {
  func read() async throws -> String?
  func save(_ key: String) async throws
  func delete() async throws
}

public struct KeychainStoreError: Error, Sendable, CustomStringConvertible {
  public enum Operation: String, Sendable {
    case read
    case save
    case delete
  }

  public let operation: Operation
  public let status: OSStatus?

  public var description: String {
    if let status {
      return "Keychain \(operation.rawValue) failed (status \(status))."
    }
    return "Keychain \(operation.rawValue) returned invalid data."
  }
}

public struct KeychainStore: WorkspaceKeyStore, @unchecked Sendable {
  static let service = "com.findmegamer.desktop"
  static let account = "workspace-access-key"

  struct SecurityCalls: @unchecked Sendable {
    let copyMatching: (CFDictionary, UnsafeMutablePointer<CFTypeRef?>?) -> OSStatus
    let add: (CFDictionary) -> OSStatus
    let update: (CFDictionary, CFDictionary) -> OSStatus
    let delete: (CFDictionary) -> OSStatus

    static let live = SecurityCalls(
      copyMatching: SecItemCopyMatching,
      add: { SecItemAdd($0, nil) },
      update: SecItemUpdate,
      delete: SecItemDelete)
  }

  private let calls: SecurityCalls

  public init() {
    calls = .live
  }

  init(calls: SecurityCalls) {
    self.calls = calls
  }

  public func read() async throws -> String? {
    var result: CFTypeRef?
    let status = calls.copyMatching(readQuery as CFDictionary, &result)
    if status == errSecItemNotFound { return nil }
    guard status == errSecSuccess else {
      throw KeychainStoreError(operation: .read, status: status)
    }
    guard let data = result as? Data, let key = String(data: data, encoding: .utf8) else {
      throw KeychainStoreError(operation: .read, status: nil)
    }
    return key
  }

  public func save(_ key: String) async throws {
    var attributes = identityQuery
    attributes[stringKey(kSecValueData)] = Data(key.utf8)
    attributes[stringKey(kSecAttrAccessible)] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
    let status = calls.add(attributes as CFDictionary)
    if status == errSecSuccess { return }
    guard status == errSecDuplicateItem else {
      throw KeychainStoreError(operation: .save, status: status)
    }

    let replacements: [String: Any] = [
      stringKey(kSecValueData): Data(key.utf8),
      stringKey(kSecAttrAccessible): kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
    ]
    let updateStatus = calls.update(identityQuery as CFDictionary, replacements as CFDictionary)
    guard updateStatus == errSecSuccess else {
      throw KeychainStoreError(operation: .save, status: updateStatus)
    }
  }

  public func delete() async throws {
    let status = calls.delete(identityQuery as CFDictionary)
    guard status == errSecSuccess || status == errSecItemNotFound else {
      throw KeychainStoreError(operation: .delete, status: status)
    }
  }

  private var identityQuery: [String: Any] {
    [
      stringKey(kSecClass): kSecClassGenericPassword,
      stringKey(kSecAttrService): Self.service,
      stringKey(kSecAttrAccount): Self.account,
      stringKey(kSecAttrSynchronizable): false,
    ]
  }

  private var readQuery: [String: Any] {
    var query = identityQuery
    query[stringKey(kSecMatchLimit)] = kSecMatchLimitOne
    query[stringKey(kSecReturnData)] = true
    return query
  }
}

private func stringKey(_ value: CFString) -> String {
  value as String
}
