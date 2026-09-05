import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct LibraryTaskStateTests {
  @Test func emptyStatesOfferConcreteActionsWithoutRepeatingTheirInstructions() {
    #expect(LibraryEmptyContext.search.detail == nil)
    #expect(LibraryEmptyContext.search.actionTitle == "Clear Search")
    #expect(LibraryEmptyContext.favorites.actionTitle == "Browse All Profiles")
    #expect(LibraryEmptyContext.firstProfile.detail == "YouTube channels · Steam games")
    #expect(LibraryEmptyContext.firstProfile.actionTitle == "Analyze Profile")
  }

  @Test func noMatchesClearsSearchWithoutDiscardingCollectionContext() {
    #expect(LibraryEmptyContext.resolve(query: "strategy", onlyCollection: true) == .search)
    #expect(LibraryEmptyContext.resolve(query: "strategy", onlyCollection: false) == .search)
  }

  @Test func emptyFavoritesOfferBroaderLibraryInsteadOfAnotherAnalysis() {
    #expect(LibraryEmptyContext.resolve(query: "  \n", onlyCollection: true) == .favorites)
    #expect(LibraryEmptyContext.resolve(query: "", onlyCollection: false) == .firstProfile)
  }

  @Test func olderInFlightAndFailedRequestsNeverHideBehindCompletedHistory() {
    let recent = (0..<3).map { _ in activityJob(status: .succeeded) }
    let oldCompleted = activityJob(status: .succeeded)
    let running = activityJob(status: .running)
    let failed = activityJob(status: .failed)
    var visibility = AnalyzeActivityVisibility()
    visibility.observe(recent + [oldCompleted, running, failed])
    #expect(visibility.visibleIDs == Set(recent.map(\.id) + [running.id, failed.id]))
  }

  @Test func completionDoesNotCollapseARequestAlreadyBeingRead() {
    let recent = (0..<3).map { _ in activityJob(status: .succeeded) }
    let running = activityJob(status: .running)
    var visibility = AnalyzeActivityVisibility()
    visibility.observe(recent + [running])
    visibility.observe(recent + [activityJob(id: running.id, status: .succeeded)])
    #expect(visibility.visibleIDs.contains(running.id))
    visibility.observe(recent)
    #expect(!visibility.visibleIDs.contains(running.id))
  }

  @Test func requestErrorsKeepTheInputVisibleAndAcceptedRequestsRevealActivity() {
    #expect(
      AnalyzeWorkspacePhase.afterSubmission(hasError: true, hasExistingProfile: false) == .request)
    #expect(
      AnalyzeWorkspacePhase.afterSubmission(hasError: false, hasExistingProfile: true) == .request)
    #expect(
      AnalyzeWorkspacePhase.afterSubmission(hasError: false, hasExistingProfile: false) == .activity
    )
  }
}

private func activityJob(id: UUID = UUID(), status: JobStatus) -> AnalysisJob {
  AnalysisJob(
    id: id, profileType: .creator, canonicalTargetID: "UCdemo",
    canonicalURL: "https://youtube.com/@demo", mode: .create, status: status,
    stage: nil, completedUnits: 0, totalUnits: 0, retryable: status == .failed,
    correlationID: "test", profileID: nil,
    createdAt: .distantPast, updatedAt: .distantPast,
    startedAt: nil, completedAt: nil, failure: nil)
}
