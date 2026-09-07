import FindMeGamerCore
import SwiftUI

struct ReanalysisSettings: View {
  @Bindable var model: SettingsModel

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Bindable var presentation: SettingsPresentation

  var body: some View {
    Section("Auto-refresh") {
      if model.isLoadingReanalysis && model.sharedSettings == nil {
        ProgressView("Loading intervals…")
      }

      Stepper(value: gameInterval, in: 1...90) {
        LabeledContent("Games · 1–90 days", value: "Every \(model.gameIntervalDays) days")
      }
      .disabled(model.isSavingReanalysis)

      Stepper(value: creatorInterval, in: 1...30) {
        LabeledContent("Creators · 1–30 days", value: "Every \(model.creatorIntervalDays) days")
      }
      .disabled(model.isSavingReanalysis)

      Label("Workspace-shared schedules", systemImage: "person.2")
        .font(.caption)
        .foregroundStyle(.secondary)

      HStack {
        Button {
          presentation.isShowingSaveConfirmation = true
        } label: {
          HStack(spacing: 6) {
            if model.isSavingReanalysis { ProgressView().controlSize(.mini) }
            Text(model.isSavingReanalysis ? "Saving…" : "Save")
          }
        }
        .buttonStyle(.borderedProminent)
        .disabled(!writesEnabled || !model.canSaveReanalysis)

        if !model.isSavingReanalysis, model.sharedSettings != nil {
          Label(
            model.canSaveReanalysis ? "Unsaved" : "Saved",
            systemImage: model.canSaveReanalysis ? "circle.fill" : "checkmark"
          )
          .font(.caption).foregroundStyle(.secondary)
        }
      }

      if let error = model.reanalysisLoadError {
        HStack {
          Label(error, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red)
          Spacer()
          Button("Try Again") {
            Task { await model.loadReanalysis() }
          }
          .disabled(model.isLoadingReanalysis)
        }
      }

      if let error = model.reanalysisActionError {
        Label(error, systemImage: "exclamationmark.triangle")
          .foregroundStyle(.red)
      }

      InlineDisclosure("Refresh activity", isExpanded: $presentation.isShowingActivity) {
        activityRow("Game", activity: model.gameActivity, error: model.activityError(for: .game))
        activityRow(
          "Creator", activity: model.creatorActivity, error: model.activityError(for: .creator))
        if model.isLoadingActivity {
          ProgressView("Loading profile activity…")
        }
      }
    }
    .confirmationDialog(
      "Save Re-analysis Settings?",
      isPresented: $presentation.isShowingSaveConfirmation,
      titleVisibility: .visible
    ) {
      Button("Save Settings") {
        Task { await model.saveReanalysis() }
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("These shared intervals affect all coworkers in this Workspace.")
    }
  }

  private var gameInterval: Binding<Int> {
    Binding(
      get: { model.gameIntervalDays },
      set: {
        model.updateReanalysis(gameIntervalDays: $0, creatorIntervalDays: model.creatorIntervalDays)
      })
  }

  private var creatorInterval: Binding<Int> {
    Binding(
      get: { model.creatorIntervalDays },
      set: {
        model.updateReanalysis(gameIntervalDays: model.gameIntervalDays, creatorIntervalDays: $0)
      })
  }

  private func activityRow(
    _ title: String, activity: ProfileAnalysisActivity, error: String?
  ) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(title)
        .font(.headline)
      LabeledContent("Last analysis", value: formatted(activity.latestAnalysis))
      LabeledContent("Next refresh", value: formatted(activity.nextReanalysis))
      if let error {
        Text(error)
          .foregroundStyle(.secondary)
      }
    }
  }

  private func formatted(_ date: Date?) -> String {
    date?.formatted(date: .abbreviated, time: .shortened) ?? "Unavailable"
  }
}
