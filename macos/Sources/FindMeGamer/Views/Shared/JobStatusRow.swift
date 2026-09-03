import FindMeGamerCore
import SwiftUI

enum AnalyzeAccessibility {
  static let profileType = "analyze.profile-type"
  static let url = "analyze.url"
  static let submit = "analyze.submit"
  static let existingProfile = "analyze.existing-profile"

  static func job(_ id: UUID) -> String { "analyze.job.\(id.uuidString)" }
}

enum JobSemanticState: Equatable {
  case progress(String)
  case succeeded
  case failed
  case superseded
}

struct AnalyzeProfileRoute: Equatable {
  let type: ProfileType
  let id: UUID

  init(type: ProfileType, id: UUID) {
    self.type = type
    self.id = id
  }

  init(existingProfile: ExistingProfile) {
    self.init(type: existingProfile.profileType, id: existingProfile.profileID)
  }

  init?(job: AnalysisJob) {
    guard job.status == .succeeded, let profileID = job.profileID else { return nil }
    self.init(type: job.profileType, id: profileID)
  }
}

struct JobStatusPresentation: Equatable {
  let state: JobSemanticState
  let failureMessage: String?
  let canRetry: Bool
  let canOpenProfile: Bool
  let canReanalyze: Bool

  init(job: AnalysisJob) {
    failureMessage = job.status == .failed ? job.failure?.message : nil
    canRetry = job.status == .failed && job.retryable
    canOpenProfile = AnalyzeProfileRoute(job: job) != nil
    canReanalyze = canOpenProfile

    switch job.status {
    case .queued:
      state = .progress("Queued")
    case .running:
      switch job.stage {
      case .fetchingData: state = .progress("Fetching Data")
      case .analyzing: state = .progress("Analyzing")
      case .finalizing: state = .progress("Finalizing")
      case nil: state = .progress("Running")
      }
    case .succeeded:
      state = .succeeded
    case .failed:
      state = .failed
    case .superseded:
      state = .superseded
    }
  }
}

enum AnalyzeActionPolicy {
  static func canSubmit(writesEnabled: Bool, isSubmitting: Bool) -> Bool {
    writesEnabled && !isSubmitting
  }

  static func canRetry(job: AnalysisJob, writesEnabled: Bool, isRetrying: Bool) -> Bool {
    writesEnabled && !isRetrying && JobStatusPresentation(job: job).canRetry
  }

  static func canOpenProfile(job: AnalysisJob) -> Bool {
    JobStatusPresentation(job: job).canOpenProfile
  }

  static func canReanalyze(
    job: AnalysisJob, writesEnabled: Bool, isReanalyzing: Bool
  ) -> Bool {
    writesEnabled && !isReanalyzing && JobStatusPresentation(job: job).canReanalyze
  }
}

struct JobStatusRow: View {
  let job: AnalysisJob
  let writesEnabled: Bool
  let isRetrying: Bool
  let isReanalyzing: Bool
  let onOpenProfile: () -> Void
  let onRetry: () -> Void
  let onReanalyze: () -> Void

  private var presentation: JobStatusPresentation { JobStatusPresentation(job: job) }

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(alignment: .firstTextBaseline) {
        Text(job.profileType.displayName)
          .font(.headline)
        Spacer()
        Text(job.createdAt, style: .relative)
          .font(.caption)
          .foregroundStyle(.secondary)
          .accessibilityLabel("Submitted \(job.createdAt.formatted())")
      }

      Text(job.canonicalURL)
        .font(.caption)
        .foregroundStyle(.secondary)
        .lineLimit(2)
        .textSelection(.enabled)

      status

      if let failureMessage = presentation.failureMessage {
        Text(failureMessage)
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      actions
    }
    .padding(.vertical, 8)
    .accessibilityIdentifier(AnalyzeAccessibility.job(job.id))
  }

  @ViewBuilder private var status: some View {
    switch presentation.state {
    case .progress(let label):
      HStack(spacing: 7) {
        ProgressView()
          .controlSize(.small)
        Text(label)
      }
    case .succeeded:
      Label("Completed", systemImage: "checkmark.circle.fill")
        .foregroundStyle(.green)
    case .failed:
      Label("Failed", systemImage: "xmark.circle.fill")
        .foregroundStyle(.red)
    case .superseded:
      Label("Superseded", systemImage: "arrow.trianglehead.2.clockwise.rotate.90")
        .foregroundStyle(.secondary)
    }
  }

  @ViewBuilder private var actions: some View {
    if presentation.canRetry || presentation.canOpenProfile {
      HStack {
        if presentation.canRetry {
          Button("Retry", action: onRetry)
            .disabled(
              !AnalyzeActionPolicy.canRetry(
                job: job, writesEnabled: writesEnabled, isRetrying: isRetrying)
            )
            .help("Retry this failed analysis")
        }
        if presentation.canOpenProfile {
          Button("Open Profile", action: onOpenProfile)
            .help("Open the completed profile")
          Button("Re-analyze", action: onReanalyze)
            .disabled(
              !AnalyzeActionPolicy.canReanalyze(
                job: job, writesEnabled: writesEnabled, isReanalyzing: isReanalyzing)
            )
            .help("Request a new analysis for this profile")
        }
      }
      .controlSize(.small)
    }
  }
}
