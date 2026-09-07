import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct JobElapsedTimePresentationTests {
  private let start = Date(timeIntervalSince1970: 1_000)

  @Test func queuedNeverPretendsToWorkEvenWithUnexpectedTimestamps() {
    for startedAt in [nil, start] {
      let timing = JobElapsedTimePresentation(
        job: job(.queued, start: startedAt, end: start.addingTimeInterval(42)))
      #expect(timing == .waiting)
      #expect(!timing.updatesLive)
      #expect(timing.label(at: start) == "Waiting")
      #expect(timing.label(at: start.addingTimeInterval(500)) == "Waiting")
    }
  }

  @Test func runningCountsFromStartNotSubmissionAndAdvances() {
    let timing = JobElapsedTimePresentation(job: job(.running, start: start))
    #expect(timing.updatesLive)
    #expect(timing.label(at: start.addingTimeInterval(5)) == "Working for 5s")
    #expect(timing.label(at: start.addingTimeInterval(65)) == "Working for 1m 5s")
  }

  @Test(arguments: [JobStatus.succeeded, .failed, .superseded])
  func allTerminalStatesFreezeAtCompletion(_ status: JobStatus) {
    let timing = JobElapsedTimePresentation(
      job: job(status, start: start, end: start.addingTimeInterval(125)))
    #expect(!timing.updatesLive)
    #expect(timing.label(at: start.addingTimeInterval(130)) == "Worked for 2m 5s")
    #expect(timing.label(at: start.addingTimeInterval(86_400)) == "Worked for 2m 5s")
  }

  @Test(arguments: [JobStatus.succeeded, .failed, .superseded])
  func missingTerminalTimestampsNeverUseNowOrChangeWatermark(_ status: JobStatus) {
    for job in [
      job(status, start: start),
      job(status, end: start.addingTimeInterval(42)),
      job(status),
    ] {
      let timing = JobElapsedTimePresentation(job: job)
      #expect(!timing.updatesLive)
      #expect(timing.label(at: start) == "Worked for —")
      #expect(timing.label(at: start.addingTimeInterval(86_400)) == "Worked for —")
    }
  }

  @Test func runningWithoutStartDoesNotInventElapsedWork() {
    let timing = JobElapsedTimePresentation(job: job(.running))
    #expect(!timing.updatesLive)
    #expect(timing.label(at: start) == "Working for —")
    #expect(timing.label(at: start.addingTimeInterval(500)) == "Working for —")
  }

  @Test func completionCapsEvenAnInconsistentRunningSnapshot() {
    let timing = JobElapsedTimePresentation(
      job: job(.running, start: start, end: start.addingTimeInterval(42)))
    #expect(!timing.updatesLive)
    #expect(timing.label(at: start.addingTimeInterval(500)) == "Worked for 42s")
  }

  @Test func lateStartMetadataAndTerminalTransitionReplaceLivePresentation() {
    #expect(!JobElapsedTimePresentation(job: job(.running)).updatesLive)
    #expect(JobElapsedTimePresentation(job: job(.running, start: start)).updatesLive)
    let completed = JobElapsedTimePresentation(
      job: job(.succeeded, start: start, end: start.addingTimeInterval(7)))
    #expect(!completed.updatesLive)
    #expect(completed.label(at: start.addingTimeInterval(100)) == "Worked for 7s")
  }

  @Test func clockSkewDoesNotDisplayNegativeDuration() {
    let running = JobElapsedTimePresentation(job: job(.running, start: start))
    #expect(running.label(at: start.addingTimeInterval(-5)) == "Working for 0s")
    let reversed = JobElapsedTimePresentation(
      job: job(.succeeded, start: start, end: start.addingTimeInterval(-5)))
    #expect(reversed.label(at: start) == "Worked for —")
  }

  @Test func invalidTimestampsAreUnavailableNotACrashOrLiveTerminalTimer() {
    for invalid in [Double.nan, .infinity, -.infinity] {
      let date = Date(timeIntervalSince1970: invalid)
      let running = JobElapsedTimePresentation(job: job(.running, start: date))
      #expect(!running.updatesLive)
      #expect(running.label(at: start) == "Working for —")
      let finished = JobElapsedTimePresentation(job: job(.succeeded, start: start, end: date))
      #expect(!finished.updatesLive)
      #expect(finished.label(at: start) == "Worked for —")
    }
  }

  @Test func formattingIncludesSecondsAndDoesNotWrapAtAnHourOrDay() {
    let examples: [(TimeInterval, String)] = [
      (0, "0s"), (0.9, "0s"), (59.99, "59s"), (60, "1m 0s"),
      (3_600, "1h 0m 0s"), (90_061, "1d 1h 1m 1s"),
    ]
    for (duration, expected) in examples {
      #expect(
        JobElapsedTimePresentation.worked(duration: duration).label(at: start)
          == "Worked for \(expected)")
    }
    #expect(
      JobElapsedTimePresentation.worked(duration: Double(Int.max)).label(at: start)
        == "Worked for —")
  }

  private func job(_ status: JobStatus, start: Date? = nil, end: Date? = nil) -> AnalysisJob {
    AnalysisJob(
      id: UUID(), profileType: .game, canonicalTargetID: "570",
      canonicalURL: "https://store.steampowered.com/app/570/", mode: .create,
      status: status, stage: nil, completedUnits: 0, totalUnits: 1, retryable: false,
      correlationID: nil, profileID: nil,
      createdAt: Date(timeIntervalSince1970: 100),
      updatedAt: Date(timeIntervalSince1970: 10_000),
      startedAt: start, completedAt: end, failure: nil)
  }
}
