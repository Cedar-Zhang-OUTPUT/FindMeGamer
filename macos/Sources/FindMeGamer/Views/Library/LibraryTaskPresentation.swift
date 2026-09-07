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
    case .favorites: "No favorites yet"
    case .firstProfile: "No profiles yet"
    }
  }

  var detail: String? {
    switch self {
    case .search: nil
    case .favorites: nil
    case .firstProfile: "YouTube channels · Steam games"
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
