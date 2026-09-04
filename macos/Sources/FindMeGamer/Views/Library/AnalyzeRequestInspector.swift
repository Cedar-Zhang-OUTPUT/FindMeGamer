import FindMeGamerCore
import SwiftUI

struct AnalyzeRequestInspector: View {
  @Bindable var model: AnalyzeRequestModel
  let writesEnabled: Bool
  let onOpenProfile: (ProfileType, UUID) -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      HStack(spacing: WorkspaceDesign.spaceS) {
        SignalMark()
        VStack(alignment: .leading, spacing: 2) {
          Text("Analyze Profile")
            .font(.title2.weight(.semibold))
            .accessibilityAddTraits(.isHeader)
          Text("Turn a source page into a shared profile.")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }

      WorkspaceSurface(style: .quiet) {
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
          Picker("Profile Type", selection: $model.targetType) {
            Text("Creator").tag(ProfileType.creator)
            Text("Game").tag(ProfileType.game)
          }
          .pickerStyle(.segmented)
          .accessibilityIdentifier(AnalyzeAccessibility.profileType)

          TextField("Steam or YouTube URL", text: $model.urlText)
            .textFieldStyle(.roundedBorder)
            .accessibilityIdentifier(AnalyzeAccessibility.url)

          HStack {
            Text(model.targetType == .game ? "Steam store page" : "YouTube channel page")
              .font(.caption)
              .foregroundStyle(.secondary)
            Spacer()
            if model.isSubmitting {
              ProgressView()
                .controlSize(.small)
                .accessibilityLabel("Submitting analysis request")
            }
            Button("Submit") {
              Task { await model.submit() }
            }
            .buttonStyle(.borderedProminent)
            .disabled(
              !AnalyzeActionPolicy.canSubmit(
                writesEnabled: writesEnabled, isSubmitting: model.isSubmitting)
            )
            .accessibilityIdentifier(AnalyzeAccessibility.submit)
            .help("Submit this profile for analysis")
          }
        }
        .padding(WorkspaceDesign.spaceM)
      }

      if let validationMessage = model.validationMessage {
        messageBanner(validationMessage)
      } else if let actionError = model.actionError {
        messageBanner(actionError)
      } else if let profile = model.existingProfile {
        existingProfileBanner(profile)
      }

      WorkspaceSectionHeader(
        "Recent Analysis",
        subtitle: "Requests keep their status while you continue working.",
        count: model.jobs.count)

      AdaptiveGlassSurface(role: .analyzeStatus) {
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 0) {
            ForEach(model.jobs) { job in
              JobStatusRow(
                job: job,
                writesEnabled: writesEnabled,
                isRetrying: model.retryingJobIDs.contains(job.id),
                isReanalyzing: model.reanalyzingJobIDs.contains(job.id),
                onOpenProfile: {
                  if let route = AnalyzeProfileRoute(job: job) {
                    onOpenProfile(route.type, route.id)
                  }
                },
                onRetry: { Task { await model.retry(job: job) } },
                onReanalyze: { Task { await model.reanalyze(.job(job)) } })

              Divider()
            }
          }
        }
      }
    }
    .padding(WorkspaceDesign.spaceM)
    .workspaceCanvas()
  }

  private func messageBanner(_ message: String) -> some View {
    Label(message, systemImage: "exclamationmark.triangle")
      .font(.callout)
      .foregroundStyle(.secondary)
      .padding(10)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
  }

  private func existingProfileBanner(_ profile: ExistingProfile) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Label("This profile already exists.", systemImage: "checkmark.circle")
      HStack {
        Button("Open Profile") {
          let route = AnalyzeProfileRoute(existingProfile: profile)
          onOpenProfile(route.type, route.id)
        }
        .help("Open the existing profile")

        Button("Re-analyze") {
          Task { await model.reanalyze(.profile(profile)) }
        }
        .disabled(
          !writesEnabled || model.reanalyzingProfileIDs.contains(profile.profileID)
        )
        .help("Request a new analysis for this profile")
      }
      .controlSize(.small)
    }
    .padding(10)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
    .accessibilityIdentifier(AnalyzeAccessibility.existingProfile)
  }
}
