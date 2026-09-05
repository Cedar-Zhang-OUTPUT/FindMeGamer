import FindMeGamerCore
import SwiftUI

struct ReanalysisSettings: View {
  @Bindable var model: SettingsModel

  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var isShowingSaveConfirmation = false

  var body: some View {
    Section("Re-analysis") {
      if model.isLoadingReanalysis && model.sharedSettings == nil {
        ProgressView("Loading intervals…")
      }

      Stepper(value: gameInterval, in: 1...90) {
        LabeledContent("Game Interval", value: "\(model.gameIntervalDays) days")
      }
      .disabled(model.isSavingReanalysis)

      Stepper(value: creatorInterval, in: 1...30) {
        LabeledContent("Creator Interval", value: "\(model.creatorIntervalDays) days")
      }
      .disabled(model.isSavingReanalysis)

      Text(
        "Creator profiles refresh automatically at least every 30 days. These schedules are shared with your workspace."
      )
      .font(.caption)
      .foregroundStyle(.secondary)

      Button("Save Re-analysis Settings") {
        isShowingSaveConfirmation = true
      }
      .buttonStyle(.borderedProminent)
      .disabled(!writesEnabled || !model.canSaveReanalysis)

      if model.isSavingReanalysis {
        ProgressView("Saving shared schedules…")
      } else if model.sharedSettings != nil {
        Text(
          model.canSaveReanalysis
            ? "You have unsaved interval changes." : "These intervals are saved for your workspace."
        )
        .font(.caption)
        .foregroundStyle(.secondary)
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

      DisclosureGroup("View profile refresh activity") {
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
      isPresented: $isShowingSaveConfirmation,
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
      Text("\(title) Profile Activity")
        .font(.headline)
      LabeledContent("Latest Profile Analysis", value: formatted(activity.latestAnalysis))
      LabeledContent("Next Profile Re-analysis", value: formatted(activity.nextReanalysis))
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
