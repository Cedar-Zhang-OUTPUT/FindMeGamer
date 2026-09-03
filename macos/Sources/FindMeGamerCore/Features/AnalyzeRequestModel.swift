import Foundation
import Observation

public enum ReanalysisSource: Sendable, Equatable {
  case job(AnalysisJob)
  case profile(ExistingProfile)
}

@MainActor
@Observable
public final class AnalyzeRequestModel {
  public var targetType: ProfileType = .creator
  public var urlText = ""
  public var inspectorPresented = false

  public private(set) var jobs: [AnalysisJob] = []
  public private(set) var existingProfile: ExistingProfile?
  public private(set) var validationMessage: String?
  public private(set) var actionError: String?
  public private(set) var isSubmitting = false
  public private(set) var retryingJobIDs: Set<UUID> = []
  public private(set) var reanalyzingJobIDs: Set<UUID> = []
  public private(set) var reanalyzingProfileIDs: Set<UUID> = []

  public var activeJobCount: Int {
    jobs.count { $0.status == .queued || $0.status == .running }
  }

  private let api: any APIService
  private let idempotencyKey: @Sendable () -> String
  private let onJobActivity: @Sendable () async -> Void
  private var jobsByID: [UUID: AnalysisJob] = [:]

  public init(
    api: any APIService,
    idempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString },
    onJobActivity: @escaping @Sendable () async -> Void = {}
  ) {
    self.api = api
    self.idempotencyKey = idempotencyKey
    self.onJobActivity = onJobActivity
  }

  public func submit() async {
    guard !isSubmitting else { return }
    let trimmedURL = urlText.trimmingCharacters(in: .whitespacesAndNewlines)
    guard validate(url: trimmedURL, for: targetType) else {
      validationMessage = validationMessage(for: targetType)
      return
    }

    validationMessage = nil
    actionError = nil
    isSubmitting = true
    defer { isSubmitting = false }

    do {
      let submission = try await api.createAnalysisJob(
        AnalysisRequest(url: trimmedURL, profileType: targetType, mode: .create),
        idempotencyKey: nextIdempotencyKey())
      await consume(submission: submission)
    } catch {
      actionError = errorMessage(error, fallback: "Could not submit analysis.")
    }
  }

  public func reanalyze(_ source: ReanalysisSource) async {
    let request: AnalysisRequest
    let identity: ReanalysisIdentity

    switch source {
    case .job(let job):
      guard job.status == .succeeded, job.profileID != nil else { return }
      identity = .job(job.id)
      request = AnalysisRequest(
        url: job.canonicalURL, profileType: job.profileType, mode: .reanalyze)
    case .profile(let profile):
      identity = .profile(profile.profileID)
      request = AnalysisRequest(
        url: profile.canonicalURL, profileType: profile.profileType, mode: .reanalyze)
    }

    guard beginReanalysis(identity) else { return }
    defer { endReanalysis(identity) }
    validationMessage = nil
    actionError = nil

    do {
      let submission = try await api.createAnalysisJob(
        request, idempotencyKey: nextIdempotencyKey())
      await consume(submission: submission)
    } catch {
      actionError = errorMessage(error, fallback: "Could not request re-analysis.")
    }
  }

  public func retry(job: AnalysisJob) async {
    guard job.status == .failed, job.retryable, retryingJobIDs.insert(job.id).inserted else {
      return
    }
    defer { retryingJobIDs.remove(job.id) }
    validationMessage = nil
    actionError = nil

    do {
      let replacement = try await api.retryAnalysisJob(
        id: job.id, idempotencyKey: nextIdempotencyKey())
      actionError = nil
      existingProfile = nil
      upsert(replacement)
      await onJobActivity()
    } catch {
      actionError = errorMessage(error, fallback: "Could not retry analysis.")
    }
  }

  public func consume(jobBatch: JobChangeBatch) {
    for change in jobBatch.changes {
      guard case .analysis(let job) = change else { continue }
      storeIfCurrent(job)
    }
    rebuildJobs()
  }

  private func consume(submission: AnalysisSubmission) async {
    switch submission {
    case .job(let job):
      actionError = nil
      existingProfile = nil
      upsert(job)
      await onJobActivity()
    case .existingProfile(let profile):
      actionError = nil
      existingProfile = profile
    }
  }

  private func upsert(_ job: AnalysisJob) {
    storeIfCurrent(job)
    rebuildJobs()
  }

  private func storeIfCurrent(_ job: AnalysisJob) {
    guard jobsByID[job.id].map({ $0.updatedAt <= job.updatedAt }) ?? true else { return }
    jobsByID[job.id] = job
  }

  private func rebuildJobs() {
    jobs = jobsByID.values.sorted {
      if $0.createdAt != $1.createdAt { return $0.createdAt > $1.createdAt }
      return $0.id.uuidString < $1.id.uuidString
    }
  }

  private enum ReanalysisIdentity {
    case job(UUID)
    case profile(UUID)
  }

  private func beginReanalysis(_ identity: ReanalysisIdentity) -> Bool {
    switch identity {
    case .job(let id): reanalyzingJobIDs.insert(id).inserted
    case .profile(let id): reanalyzingProfileIDs.insert(id).inserted
    }
  }

  private func endReanalysis(_ identity: ReanalysisIdentity) {
    switch identity {
    case .job(let id): reanalyzingJobIDs.remove(id)
    case .profile(let id): reanalyzingProfileIDs.remove(id)
    }
  }

  private func nextIdempotencyKey() -> String {
    let candidate = idempotencyKey()
    return UUID(uuidString: candidate) == nil ? UUID().uuidString : candidate
  }

  private func validationMessage(for type: ProfileType) -> String {
    switch type {
    case .game: "Enter a Steam game page URL."
    case .creator: "Enter a YouTube creator page URL."
    }
  }

  private func validate(url: String, for type: ProfileType) -> Bool {
    guard
      let components = URLComponents(string: url),
      components.scheme?.lowercased() == "https",
      components.user == nil,
      components.password == nil,
      components.port == nil,
      let host = components.host?.lowercased()
    else { return false }

    let path = components.path.split(separator: "/", omittingEmptySubsequences: true)
    switch type {
    case .game:
      guard host == "store.steampowered.com", path.count >= 2, path[0] == "app" else {
        return false
      }
      return !path[1].isEmpty && path[1].allSatisfy(\.isASCIIWholeNumber)
        && UInt64(path[1]) != nil && UInt64(path[1]) != 0
    case .creator:
      guard host == "youtube.com" || host == "www.youtube.com" else { return false }
      if path.count == 2, path[0] == "channel" {
        return path[1].hasPrefix("UC") && path[1].count > 2
      }
      return path.count == 1 && path[0].hasPrefix("@") && path[0].count > 1
    }
  }

  private func errorMessage(_ error: any Error, fallback: String) -> String {
    (error as? APIError)?.description ?? fallback
  }
}

extension Character {
  fileprivate var isASCIIWholeNumber: Bool { isASCII && isWholeNumber }
}
