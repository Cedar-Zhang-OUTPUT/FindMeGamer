import CoreFoundation
import Dispatch
import Foundation
import Security
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct KeychainStoreTests {
  @Test func readUsesTheExactScopedGenericPasswordQuery() async throws {
    let security = RecordingSecurityCalls(
      copyStatus: errSecSuccess, copyData: Data("saved-key".utf8))
    let store = KeychainStore(calls: security.calls)

    #expect(try await store.read() == "saved-key")

    let query = try #require(security.copyQueries.first)
    expectIdentity(query)
    #expect(query[stringKey(kSecMatchLimit)] as? String == stringValue(kSecMatchLimitOne))
    #expect(query[stringKey(kSecReturnData)] as? Bool == true)
    #expect(query[stringKey(kSecAttrSynchronizable)] as? Bool == false)
  }

  @Test func readDistinguishesMissingInvalidDataAndSecurityFailureSafely() async throws {
    let missingSecurity = RecordingSecurityCalls(copyStatus: errSecItemNotFound)
    let missing = KeychainStore(calls: missingSecurity.calls)
    #expect(try await missing.read() == nil)

    for security in [
      RecordingSecurityCalls(copyStatus: errSecSuccess, copyData: Data([0xFF])),
      RecordingSecurityCalls(copyStatus: errSecAuthFailed),
    ] {
      let store = KeychainStore(calls: security.calls)
      do {
        _ = try await store.read()
        Issue.record("Expected a safe Keychain read failure")
      } catch {
        let description = String(describing: error)
        #expect(description.contains("read"))
        #expect(!description.contains("workspace-access-key"))
        #expect(!description.contains("saved-key"))
      }
    }
  }

  @Test func saveAddsDeviceLocalNonSynchronizableUTF8Data() async throws {
    let security = RecordingSecurityCalls(addStatuses: [errSecSuccess])
    let store = KeychainStore(calls: security.calls)

    try await store.save("EXACT-KEY-CANARY")

    let attributes = try #require(security.addQueries.first)
    expectIdentity(attributes)
    #expect(attributes[stringKey(kSecValueData)] as? Data == Data("EXACT-KEY-CANARY".utf8))
    #expect(
      attributes[stringKey(kSecAttrAccessible)] as? String
        == stringValue(kSecAttrAccessibleWhenUnlockedThisDeviceOnly))
    #expect(attributes[stringKey(kSecAttrSynchronizable)] as? Bool == false)
    #expect(security.updateCalls.isEmpty)
  }

  @Test func duplicateSaveUpdatesOnlyTheExactItemWithoutDeletingFirst() async throws {
    let security = RecordingSecurityCalls(addStatuses: [errSecDuplicateItem])
    let store = KeychainStore(calls: security.calls)

    try await store.save("replacement-key")

    let update = try #require(security.updateCalls.first)
    expectIdentity(update.query)
    #expect(update.query[stringKey(kSecAttrSynchronizable)] as? Bool == false)
    #expect(update.attributes[stringKey(kSecValueData)] as? Data == Data("replacement-key".utf8))
    #expect(
      update.attributes[stringKey(kSecAttrAccessible)] as? String
        == stringValue(kSecAttrAccessibleWhenUnlockedThisDeviceOnly))
    #expect(security.deleteQueries.isEmpty)
  }

  @Test func deleteUsesTheExactItemAndTreatsNotFoundAsSuccess() async throws {
    for status in [errSecSuccess, errSecItemNotFound] {
      let security = RecordingSecurityCalls(deleteStatus: status)
      let store = KeychainStore(calls: security.calls)

      try await store.delete()

      let query = try #require(security.deleteQueries.first)
      expectIdentity(query)
      #expect(query[stringKey(kSecAttrSynchronizable)] as? Bool == false)
      #expect(query[stringKey(kSecReturnData)] == nil)
    }
  }

  @Test func writeFailuresExposeOnlySafeOperationAndStatus() async {
    let security = RecordingSecurityCalls(
      addStatuses: [errSecInteractionNotAllowed], deleteStatus: errSecAuthFailed)
    let store = KeychainStore(calls: security.calls)

    for operation in [
      { try await store.save("WRITE-KEY-CANARY") },
      { try await store.delete() },
    ] as [() async throws -> Void] {
      do {
        try await operation()
        Issue.record("Expected Keychain operation failure")
      } catch {
        let description = String(describing: error)
        #expect(description.contains("Keychain"))
        #expect(!description.contains("WRITE-KEY-CANARY"))
        #expect(!description.contains("workspace-access-key"))
      }
    }
  }
}

@Suite(.serialized)
struct ConnectivityMonitorTests {
  @Test func startsOnceMapsUpdatesAndCancelsOnce() async {
    let recorder = PathCallRecorder()
    let monitor = ConnectivityMonitor(
      calls: recorder.calls, queue: DispatchQueue(label: "connectivity-test"))
    let values = LockedBooleans()

    monitor.start { values.append($0) }
    monitor.start { _ in Issue.record("A second observer must not be installed") }
    recorder.emit(false)
    recorder.emit(true)
    monitor.cancel()
    monitor.cancel()
    recorder.emit(false)

    #expect(recorder.startCount == 1)
    #expect(recorder.handlerInstallCount == 1)
    #expect(recorder.cancelCount == 1)
    #expect(values.values == [false, true])
    #expect(recorder.queueLabels == ["connectivity-test"])
  }

  @Test func deinitializationCancelsAStartedMonitorWithoutRetainingItsObserver() {
    let recorder = PathCallRecorder()
    weak var weakMonitor: ConnectivityMonitor?
    do {
      let monitor = ConnectivityMonitor(
        calls: recorder.calls, queue: DispatchQueue(label: "connectivity-lifetime-test"))
      weakMonitor = monitor
      monitor.start { _ in }
    }

    #expect(weakMonitor == nil)
    #expect(recorder.cancelCount == 1)
  }
}

private func expectIdentity(_ query: [String: Any]) {
  #expect(query[stringKey(kSecClass)] as? String == stringValue(kSecClassGenericPassword))
  #expect(query[stringKey(kSecAttrService)] as? String == "com.findmegamer.desktop")
  #expect(query[stringKey(kSecAttrAccount)] as? String == "workspace-access-key")
}

private func stringKey(_ value: CFString) -> String { value as String }
private func stringValue(_ value: CFString) -> String { value as String }

private final class RecordingSecurityCalls: @unchecked Sendable {
  private let lock = NSLock()
  private let copyStatus: OSStatus
  private let copyData: Data?
  private var pendingAddStatuses: [OSStatus]
  private let updateStatus: OSStatus
  private let deleteStatus: OSStatus
  private var storedCopyQueries: [[String: Any]] = []
  private var storedAddQueries: [[String: Any]] = []
  private var storedUpdateCalls: [(query: [String: Any], attributes: [String: Any])] = []
  private var storedDeleteQueries: [[String: Any]] = []

  init(
    copyStatus: OSStatus = errSecItemNotFound,
    copyData: Data? = nil,
    addStatuses: [OSStatus] = [],
    updateStatus: OSStatus = errSecSuccess,
    deleteStatus: OSStatus = errSecSuccess
  ) {
    self.copyStatus = copyStatus
    self.copyData = copyData
    self.pendingAddStatuses = addStatuses
    self.updateStatus = updateStatus
    self.deleteStatus = deleteStatus
  }

  var copyQueries: [[String: Any]] { lock.withLock { storedCopyQueries } }
  var addQueries: [[String: Any]] { lock.withLock { storedAddQueries } }
  var updateCalls: [(query: [String: Any], attributes: [String: Any])] {
    lock.withLock { storedUpdateCalls }
  }
  var deleteQueries: [[String: Any]] { lock.withLock { storedDeleteQueries } }

  var calls: KeychainStore.SecurityCalls {
    KeychainStore.SecurityCalls(
      copyMatching: { [weak self] query, result in self?.copy(query, result) ?? errSecNotAvailable
      },
      add: { [weak self] query in self?.add(query) ?? errSecNotAvailable },
      update: { [weak self] query, attributes in
        self?.update(query, attributes) ?? errSecNotAvailable
      },
      delete: { [weak self] query in self?.delete(query) ?? errSecNotAvailable })
  }

  private func copy(
    _ query: CFDictionary, _ result: UnsafeMutablePointer<CFTypeRef?>?
  ) -> OSStatus {
    lock.withLock { storedCopyQueries.append(dictionary(query)) }
    if copyStatus == errSecSuccess, let copyData {
      result?.pointee = copyData as CFData
    }
    return copyStatus
  }

  private func add(_ query: CFDictionary) -> OSStatus {
    lock.withLock {
      storedAddQueries.append(dictionary(query))
      return pendingAddStatuses.isEmpty ? errSecSuccess : pendingAddStatuses.removeFirst()
    }
  }

  private func update(_ query: CFDictionary, _ attributes: CFDictionary) -> OSStatus {
    lock.withLock {
      storedUpdateCalls.append((dictionary(query), dictionary(attributes)))
    }
    return updateStatus
  }

  private func delete(_ query: CFDictionary) -> OSStatus {
    lock.withLock { storedDeleteQueries.append(dictionary(query)) }
    return deleteStatus
  }

  private func dictionary(_ value: CFDictionary) -> [String: Any] {
    value as NSDictionary as? [String: Any] ?? [:]
  }
}

private final class PathCallRecorder: @unchecked Sendable {
  private let lock = NSLock()
  private var handler: (@Sendable (Bool) -> Void)?
  private var starts = 0
  private var installs = 0
  private var cancellations = 0
  private var labels: [String] = []

  var startCount: Int { lock.withLock { starts } }
  var handlerInstallCount: Int { lock.withLock { installs } }
  var cancelCount: Int { lock.withLock { cancellations } }
  var queueLabels: [String] { lock.withLock { labels } }

  var calls: ConnectivityMonitor.Calls {
    ConnectivityMonitor.Calls(
      setUpdateHandler: { [weak self] handler in
        self?.lock.withLock {
          self?.installs += 1
          self?.handler = handler
        }
      },
      start: { [weak self] queue in
        self?.lock.withLock {
          self?.starts += 1
          self?.labels.append(queue.label)
        }
      },
      cancel: { [weak self] in
        self?.lock.withLock { self?.cancellations += 1 }
      })
  }

  func emit(_ online: Bool) {
    lock.withLock { handler }?(online)
  }
}

private final class LockedBooleans: @unchecked Sendable {
  private let lock = NSLock()
  private var storage: [Bool] = []

  var values: [Bool] { lock.withLock { storage } }

  func append(_ value: Bool) {
    lock.withLock { storage.append(value) }
  }
}
