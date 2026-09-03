import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct AnalyzeRequestPresentationTests {
  @Test func accessibilityContractUsesStableExactIdentifiers() {
    let id = UUID(uuidString: "70000000-0000-4000-8000-000000000001")!
    #expect(AnalyzeAccessibility.profileType == "analyze.profile-type")
    #expect(AnalyzeAccessibility.url == "analyze.url")
    #expect(AnalyzeAccessibility.submit == "analyze.submit")
    #expect(AnalyzeAccessibility.existingProfile == "analyze.existing-profile")
    #expect(AnalyzeAccessibility.job(id) == "analyze.job.\(id.uuidString)")
  }

  @Test func statusPresentationUsesExactStagesAndOnlySafePublicFailure() {
    #expect(JobStatusPresentation(job: job(status: .queued)).state == .progress("Queued"))
    #expect(
      JobStatusPresentation(job: job(status: .running, stage: .fetchingData)).state
        == .progress("Fetching Data"))
    #expect(
      JobStatusPresentation(job: job(status: .running, stage: .analyzing)).state
        == .progress("Analyzing"))
    #expect(
      JobStatusPresentation(job: job(status: .running, stage: .finalizing)).state
        == .progress("Finalizing"))
    #expect(JobStatusPresentation(job: job(status: .succeeded)).state == .succeeded)
    #expect(JobStatusPresentation(job: job(status: .superseded)).state == .superseded)

    let failed = JobStatusPresentation(
      job: job(
        status: .failed, retryable: true,
        failure: JobFailure(code: "internal_detail", message: "Safe coworker message.")))
    #expect(failed.state == .failed)
    #expect(failed.failureMessage == "Safe coworker message.")
    #expect(failed.canRetry)
  }

  @Test func actionPolicyKeepsReadsOfflineAndDisablesOnlyAffectedWrites() {
    let profileID = UUID(uuidString: "80000000-0000-4000-8000-000000000001")!
    let successful = job(status: .succeeded, profileID: profileID)
    let retryable = job(status: .failed, retryable: true)
    let active = job(status: .running)

    #expect(!AnalyzeActionPolicy.canSubmit(writesEnabled: false, isSubmitting: false))
    #expect(!AnalyzeActionPolicy.canSubmit(writesEnabled: true, isSubmitting: true))
    #expect(AnalyzeActionPolicy.canSubmit(writesEnabled: true, isSubmitting: false))
    #expect(!AnalyzeActionPolicy.canRetry(job: retryable, writesEnabled: false, isRetrying: false))
    #expect(!AnalyzeActionPolicy.canRetry(job: retryable, writesEnabled: true, isRetrying: true))
    #expect(AnalyzeActionPolicy.canRetry(job: retryable, writesEnabled: true, isRetrying: false))
    #expect(!AnalyzeActionPolicy.canRetry(job: active, writesEnabled: true, isRetrying: false))
    #expect(AnalyzeActionPolicy.canOpenProfile(job: successful))
    #expect(!AnalyzeActionPolicy.canOpenProfile(job: active))
    #expect(
      !AnalyzeActionPolicy.canReanalyze(
        job: successful, writesEnabled: false, isReanalyzing: false))
    #expect(
      !AnalyzeActionPolicy.canReanalyze(
        job: successful, writesEnabled: true, isReanalyzing: true))
    #expect(
      AnalyzeActionPolicy.canReanalyze(
        job: successful, writesEnabled: true, isReanalyzing: false))
    #expect(
      !AnalyzeActionPolicy.canReanalyze(
        job: active, writesEnabled: true, isReanalyzing: false))
  }

  @Test func profileRoutesPreserveExactExistingAndCompletedIdentities() {
    let existingID = UUID(uuidString: "90000000-0000-4000-8000-000000000001")!
    let completedID = UUID(uuidString: "90000000-0000-4000-8000-000000000002")!
    let existing = ExistingProfile(
      profileID: existingID, profileType: .game, canonicalTargetID: "730",
      canonicalURL: "https://store.steampowered.com/app/730")

    #expect(AnalyzeProfileRoute(existingProfile: existing) == .init(type: .game, id: existingID))
    #expect(
      AnalyzeProfileRoute(job: job(status: .succeeded, profileID: completedID))
        == .init(type: .creator, id: completedID))
    #expect(AnalyzeProfileRoute(job: job(status: .succeeded)) == nil)
    #expect(AnalyzeProfileRoute(job: job(status: .running, profileID: completedID)) == nil)
  }
}

private func job(
  status: JobStatus,
  stage: AnalysisStage? = nil,
  retryable: Bool = false,
  profileID: UUID? = nil,
  failure: JobFailure? = nil
) -> AnalysisJob {
  AnalysisJob(
    id: UUID(), profileType: .creator, canonicalTargetID: "UC123",
    canonicalURL: "https://youtube.com/channel/UC123", mode: .create, status: status,
    stage: stage, completedUnits: 0, totalUnits: 1, retryable: retryable,
    correlationID: "must-not-be-presented", profileID: profileID,
    createdAt: Date(timeIntervalSince1970: 100), updatedAt: Date(timeIntervalSince1970: 100),
    startedAt: nil, completedAt: nil, failure: failure)
}
