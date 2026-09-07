import FindMeGamerCore
import Foundation

/// Work time is distinct from submission age and the change-feed watermark.
enum JobElapsedTimePresentation: Equatable {
  case waiting
  case working(since: Date?)
  case worked(duration: TimeInterval?)

  init(job: AnalysisJob) {
    let start = job.startedAt.flatMap { $0.timeIntervalSince1970.isFinite ? $0 : nil }
    switch job.status {
    case .queued:
      self = .waiting
    case .running where job.completedAt == nil:
      self = .working(since: start)
    case .running, .succeeded, .failed, .superseded:
      // A completion timestamp also caps an inconsistent, still-running snapshot.
      // Never substitute `now`, createdAt, or updatedAt for missing work timestamps.
      if let start, let end = job.completedAt {
        let duration = end.timeIntervalSince(start)
        self = .worked(duration: Self.isValid(duration) ? duration : nil)
      } else {
        self = .worked(duration: nil)
      }
    }
  }

  var updatesLive: Bool {
    if case .working(.some) = self { return true }
    return false
  }

  func label(at now: Date) -> String {
    switch self {
    case .waiting:
      return "Waiting"
    case .working(let start):
      // Small server/client clock differences must not produce a negative timer.
      let elapsed = start.map { now.timeIntervalSince($0) }
      let duration = elapsed.flatMap { $0.isFinite ? max(0, $0) : nil }
      return "Working for \(Self.format(duration))"
    case .worked(let duration):
      return "Worked for \(Self.format(duration))"
    }
  }

  var detail: String {
    switch self {
    case .waiting:
      "Waiting to start; queue time is not work time."
    case .working(.some):
      "Elapsed since the server recorded the start of this analysis."
    case .working(nil):
      "Working; the server did not provide a valid start time."
    case .worked(.some):
      "Time between the recorded start and completion; excludes queue time."
    case .worked(nil):
      "Work duration unavailable: the analysis did not start or its timestamps are missing or invalid."
    }
  }

  private static func isValid(_ duration: TimeInterval) -> Bool {
    duration.isFinite && duration >= 0 && duration < Double(Int.max)
  }

  private static func format(_ duration: TimeInterval?) -> String {
    guard let duration, isValid(duration) else { return "—" }
    let seconds = Int(duration.rounded(.down))
    let minutes = (seconds / 60) % 60
    let hours = (seconds / 3_600) % 24
    let days = seconds / 86_400
    if days > 0 { return "\(days)d \(hours)h \(minutes)m \(seconds % 60)s" }
    if hours > 0 { return "\(hours)h \(minutes)m \(seconds % 60)s" }
    if seconds >= 60 { return "\(minutes)m \(seconds % 60)s" }
    return "\(seconds)s"
  }
}
