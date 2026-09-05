import FindMeGamerCore
import SwiftUI

struct AnalyzeRequestInspector: View {
  @Bindable var model: AnalyzeRequestModel
  @Binding var phase: AnalyzeWorkspacePhase
  let writesEnabled: Bool
  let onOpenProfile: (ProfileType, UUID) -> Void

  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var olderRequestsExpanded = false
  @State private var activityVisibility = AnalyzeActivityVisibility()

  private var retainedActivityIDs: Set<UUID> { activityVisibility.visibleIDs }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      HStack(alignment: .top) {
        VStack(alignment: .leading, spacing: 4) {
          Text("Analyze a profile").font(.title3.weight(.semibold))
            .accessibilityAddTraits(.isHeader)
          Text("From source to shared knowledge.").font(.caption).foregroundStyle(.secondary)
        }
        Spacer(minLength: 4)
        Button {
          model.inspectorPresented = false
        } label: {
          Image(systemName: "xmark")
        }
        .buttonStyle(.plain)
        .accessibilityLabel("Close analysis panel")
        .help("Close this panel; requests continue in the background")
      }
      Picker("Analysis workspace", selection: Binding(get: { phase }, set: { setPhase($0) })) {
        Text("New Request").tag(AnalyzeWorkspacePhase.request)
        Text("Activity · \(model.jobs.count)").tag(AnalyzeWorkspacePhase.activity)
      }
      .pickerStyle(.segmented)
      .disabled(model.isSubmitting)

      if !writesEnabled {
        Label(
          "Reconnect to submit or retry. Existing activity is still available.",
          systemImage: "wifi.slash"
        )
        .font(.caption).foregroundStyle(.secondary)
      }
      ScrollView {
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
          switch phase {
          case .request: requestForm
          case .activity: activity
          }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
      }
    }
    .padding(WorkspaceDesign.spaceM)
    .workspaceCanvas()
    .onChange(of: model.jobs, initial: true) { _, jobs in
      // Once a request is visible, completion must not hide it while the user is reading.
      activityVisibility.observe(jobs)
    }
  }

  private var requestForm: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      VStack(alignment: .leading, spacing: 8) {
        Text("What are you adding?").font(.headline)
        Picker("Profile Type", selection: $model.targetType) {
          Text("Creator").tag(ProfileType.creator)
          Text("Game").tag(ProfileType.game)
        }
        .pickerStyle(.segmented).disabled(model.isSubmitting)
        .accessibilityIdentifier(AnalyzeAccessibility.profileType)
      }
      VStack(alignment: .leading, spacing: 8) {
        Text(model.targetType == .game ? "Steam game URL" : "YouTube channel URL").font(.headline)
        TextField(
          model.targetType == .game
            ? "https://store.steampowered.com/app/…" : "https://youtube.com/@…",
          text: $model.urlText
        )
        .textFieldStyle(.roundedBorder).controlSize(.large)
        .disabled(model.isSubmitting)
        .accessibilityIdentifier(AnalyzeAccessibility.url)
        .onSubmit(submit)
        Text("The analysis will be saved to your shared Library.")
          .font(.caption).foregroundStyle(.secondary)
      }
      if let message = model.validationMessage ?? model.actionError {
        messageBanner(message)
      } else if let profile = model.existingProfile {
        existingProfileBanner(profile)
      }

      Button(action: submit) {
        HStack(spacing: 8) {
          if model.isSubmitting { ProgressView().controlSize(.small) }
          Text(model.isSubmitting ? "Submitting…" : "Analyze Profile")
        }
        .frame(maxWidth: .infinity)
      }
      .buttonStyle(.borderedProminent).controlSize(.large)
      .disabled(
        !AnalyzeActionPolicy.canSubmit(
          writesEnabled: writesEnabled, isSubmitting: model.isSubmitting)
      )
      .accessibilityIdentifier(AnalyzeAccessibility.submit)

      Divider()
      VStack(alignment: .leading, spacing: 8) {
        Text("You can keep working").font(.subheadline.weight(.medium))
        Text(
          "Requests continue when you close this panel. Check Activity to open completed profiles or retry a failed request."
        )
        .font(.caption).foregroundStyle(.secondary)
        if !model.jobs.isEmpty {
          Button("View Activity (\(model.jobs.count))") { setPhase(.activity) }.buttonStyle(.link)
        }
      }
    }
  }

  private var activity: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      if let error = model.actionError { messageBanner(error) }
      if model.jobs.isEmpty {
        ContentUnavailableView {
          Label("No requests yet", systemImage: "tray")
        } description: {
          Text("Add a source page to create your first profile.")
        } actions: {
          Button("New Request") { setPhase(.request) }.buttonStyle(.borderedProminent)
        }
      } else {
        VStack(alignment: .leading, spacing: 4) {
          Text(model.activeJobCount > 0 ? "\(model.activeJobCount) in progress" : "Recent requests")
            .font(.headline)
          Text("Open a completed profile to review what was learned.").font(.caption)
            .foregroundStyle(.secondary)
        }
        ForEach(model.jobs.filter { retainedActivityIDs.contains($0.id) }) { job in
          jobRow(job)
          Divider()
        }
        if model.jobs.count > retainedActivityIDs.count {
          DisclosureGroup(
            "Older Requests (\(model.jobs.count - retainedActivityIDs.count))",
            isExpanded: $olderRequestsExpanded
          ) {
            ForEach(model.jobs.filter { !retainedActivityIDs.contains($0.id) }) { job in
              jobRow(job)
              Divider()
            }
          }
        }
        Button("Edit Source / New Request") { setPhase(.request) }.buttonStyle(.bordered)
        Text("Your last source URL is kept when you return.").font(.caption).foregroundStyle(
          .secondary)
      }
    }
  }

  private func jobRow(_ job: AnalysisJob) -> some View {
    JobStatusRow(
      job: job, writesEnabled: writesEnabled,
      isRetrying: model.retryingJobIDs.contains(job.id),
      isReanalyzing: model.reanalyzingJobIDs.contains(job.id),
      onOpenProfile: {
        if let route = AnalyzeProfileRoute(job: job) { onOpenProfile(route.type, route.id) }
      },
      onRetry: { Task { await model.retry(job: job) } },
      onReanalyze: { Task { await model.reanalyze(.job(job)) } })
  }

  private func submit() {
    guard
      AnalyzeActionPolicy.canSubmit(writesEnabled: writesEnabled, isSubmitting: model.isSubmitting)
    else { return }
    Task {
      await model.submit()
      setPhase(
        .afterSubmission(
          hasError: model.validationMessage != nil || model.actionError != nil,
          hasExistingProfile: model.existingProfile != nil))
    }
  }

  private func setPhase(_ newPhase: AnalyzeWorkspacePhase) {
    withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
      phase = newPhase
    }
  }

  private func messageBanner(_ message: String) -> some View {
    Label(message, systemImage: "exclamationmark.triangle")
      .font(.callout).foregroundStyle(.primary).textSelection(.enabled)
      .padding(12).frame(maxWidth: .infinity, alignment: .leading)
      .background(Color.red.opacity(0.07), in: RoundedRectangle(cornerRadius: 8))
  }

  private func existingProfileBanner(_ profile: ExistingProfile) -> some View {
    WorkspaceSurface(style: .quiet) {
      VStack(alignment: .leading, spacing: 10) {
        Label("Already in your Library", systemImage: "checkmark.circle").font(.headline)
        Text("Review the saved profile, or request a fresh analysis.").font(.caption)
          .foregroundStyle(.secondary)
        HStack {
          Button("Open Profile") {
            let route = AnalyzeProfileRoute(existingProfile: profile)
            onOpenProfile(route.type, route.id)
          }
          Button("Re-analyze") {
            Task {
              await model.reanalyze(.profile(profile))
            }
          }
          .disabled(!writesEnabled || model.reanalyzingProfileIDs.contains(profile.profileID))
        }
        .controlSize(.small)
      }
      .padding(12)
    }
    .accessibilityIdentifier(AnalyzeAccessibility.existingProfile)
  }
}
