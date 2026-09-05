import FindMeGamerCore
import Foundation

enum LibraryEmptyContext: Equatable {
  case search
  case favorites
  case firstProfile

  static func resolve(query: String, onlyCollection: Bool) -> Self {
    if !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return .search }
    return onlyCollection ? .favorites : .firstProfile
  }

  var title: String {
    switch self {
    case .search: "No matching profiles"
    case .favorites: "Your favorites start here"
    case .firstProfile: "Build your first profile"
    }
  }

  var detail: String {
    switch self {
    case .search: "Try another name or clear your search. Your other filters will stay in place."
    case .favorites: "Save profiles with the heart button to find them here later."
    case .firstProfile:
      "Add a YouTube channel or Steam game page to turn a source into a reusable profile."
    }
  }

  var actionTitle: String {
    switch self {
    case .search: "Clear Search"
    case .favorites: "Browse All Profiles"
    case .firstProfile: "Analyze Profile"
    }
  }
}

enum AnalyzeWorkspacePhase: String, CaseIterable {
  case request
  case activity

  static func afterSubmission(hasError: Bool, hasExistingProfile: Bool) -> Self {
    hasError || hasExistingProfile ? .request : .activity
  }
}

struct AnalyzeActivityVisibility {
  private(set) var visibleIDs: Set<UUID> = []

  mutating func observe(_ jobs: [AnalysisJob]) {
    visibleIDs.formUnion(jobs.prefix(3).map(\.id))
    visibleIDs.formUnion(
      jobs.filter {
        $0.status == .queued || $0.status == .running || $0.status == .failed
      }.map(\.id))
    visibleIDs.formIntersection(jobs.map(\.id))
  }
}
