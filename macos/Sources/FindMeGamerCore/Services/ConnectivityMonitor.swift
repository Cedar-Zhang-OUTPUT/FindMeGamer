import Dispatch
import Foundation
import Network

public protocol ConnectivityMonitoring: Sendable {
  func start(handler: @escaping @Sendable (Bool) -> Void)
  func cancel()
}

public final class ConnectivityMonitor: ConnectivityMonitoring, @unchecked Sendable {
  struct Calls: @unchecked Sendable {
    let setUpdateHandler: (@escaping @Sendable (Bool) -> Void) -> Void
    let start: (DispatchQueue) -> Void
    let cancel: () -> Void
  }

  private let calls: Calls
  private let queue: DispatchQueue
  private let lock = NSLock()
  private var handler: (@Sendable (Bool) -> Void)?
  private var started = false
  private var stopped = false

  public convenience init() {
    let monitor = NWPathMonitor()
    self.init(
      calls: Calls(
        setUpdateHandler: { callback in
          monitor.pathUpdateHandler = { path in
            callback(path.status == .satisfied)
          }
        },
        start: { monitor.start(queue: $0) },
        cancel: { monitor.cancel() }),
      queue: DispatchQueue(label: "com.findmegamer.desktop.connectivity"))
  }

  init(calls: Calls, queue: DispatchQueue) {
    self.calls = calls
    self.queue = queue
  }

  public func start(handler: @escaping @Sendable (Bool) -> Void) {
    let shouldStart = lock.withLock { () -> Bool in
      guard !started, !stopped else { return false }
      started = true
      self.handler = handler
      return true
    }
    guard shouldStart else { return }

    calls.setUpdateHandler { [weak self] online in
      self?.emit(online)
    }
    calls.start(queue)
  }

  public func cancel() {
    let shouldCancel = lock.withLock { () -> Bool in
      guard started, !stopped else { return false }
      stopped = true
      handler = nil
      return true
    }
    if shouldCancel { calls.cancel() }
  }

  deinit {
    cancel()
  }

  private func emit(_ online: Bool) {
    let callback = lock.withLock { stopped ? nil : handler }
    callback?(online)
  }
}
