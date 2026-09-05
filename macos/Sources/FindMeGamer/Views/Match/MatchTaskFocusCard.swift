import FindMeGamerCore
import SwiftUI

struct MatchTaskFocusCard: View {
  @Bindable var model: MatchModel
  let task: MatchTask
  let writesEnabled: Bool
  let onOpenGame: () -> Void
  var onNewMatch: () -> Void = {}
  var onAddCreators: () -> Void = {}
  var onFocusTask: (UUID) -> Void = { _ in }

  private var presentation: MatchHistoryPresentation {
    MatchHistoryPresentation(
      task: task, modelCanRetry: model.canRetry(task: task), writesEnabled: writesEnabled)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
      HStack(spacing: 14) {
        AsyncArtwork(
          url: ArtworkURLPolicy.validated(task.game.coverURL.flatMap(URL.init(string:))),
          fallbackSystemImage: "gamecontroller.fill"
        )
        .frame(width: 70, height: 54)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay {
          RoundedRectangle(cornerRadius: 12).strokeBorder(Color.white.opacity(0.16))
        }
        Button(action: onOpenGame) {
          Text(task.game.name)
            .font(.headline)
            .foregroundStyle(.white)
        }
        .buttonStyle(.plain)
        .help("Review the Game Profile used for this match")
        Spacer(minLength: 0)
      }
      taskState
      if let message = model.actionError {
        Label(message, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(Color(red: 1, green: 0.72, blue: 0.66))
          .textSelection(.enabled)
      }
    }
    .padding(24)
    .frame(maxWidth: .infinity, alignment: .topLeading)
    .modifier(MatchInkSurface())
    .accessibilityIdentifier("match.focused-task")
  }

  @ViewBuilder private var taskState: some View {
    switch presentation.semantic {
    case .progress(let stage):
      VStack(alignment: .leading, spacing: 10) {
        HStack(spacing: 9) {
          ProgressView().controlSize(.small)
          Text(stage).font(.title2.weight(.semibold))
        }
        Label("Running in background", systemImage: "arrow.triangle.2.circlepath")
          .font(.caption)
          .foregroundStyle(Color.white.opacity(0.72))
      }
    case .succeeded(let count):
      VStack(alignment: .leading, spacing: 12) {
        Text(count > 0 ? "\(count) \(count == 1 ? "creator" : "creators")" : "No suitable creators")
          .font(.system(size: 29, weight: .semibold, design: .rounded)).tracking(-0.8)
        if count > 0 {
          NavigationLink(value: MatchRoute.result(task.id)) {
            Label("Review creators", systemImage: "arrow.right")
              .foregroundStyle(.white)
          }
          .buttonStyle(.borderedProminent)
          .tint(MatchInkControlColors.actionBackground)
          .controlSize(.large)
        } else {
          HStack(spacing: 12) {
            Button("Add creators", systemImage: "plus", action: onAddCreators)
              .buttonStyle(.borderedProminent)
              .tint(MatchInkControlColors.actionBackground)
              .disabled(!writesEnabled)
            Button("New match", action: onNewMatch).buttonStyle(.bordered)
          }
        }
      }
    case .failed(let message):
      VStack(alignment: .leading, spacing: 12) {
        Label("Match failed", systemImage: "exclamationmark.triangle")
          .font(.title3.weight(.semibold))
        Text(message)
          .font(.callout)
          .foregroundStyle(Color.white.opacity(0.8))
          .textSelection(.enabled)
        if presentation.showsRetry {
          Button {
            Task { await model.retry(task: task) }
          } label: {
            Text(model.retryingTaskIDs.contains(task.id) ? "Retrying…" : "Retry match")
              .foregroundStyle(.white)
          }
          .buttonStyle(.borderedProminent)
          .tint(MatchInkControlColors.actionBackground)
          .disabled(!presentation.canRetry)
        } else {
          Button("New match", action: onNewMatch)
            .buttonStyle(.bordered)
        }
      }
    case .superseded:
      VStack(alignment: .leading, spacing: 10) {
        Label("Replaced by a newer match", systemImage: "arrow.triangle.branch")
          .font(.title3.weight(.semibold))
        if let latest = MatchTaskSuccessorPolicy.latestSuccessor(of: task, in: model.tasks) {
          Button("Open latest", systemImage: "arrow.right") { onFocusTask(latest.id) }
            .buttonStyle(.borderedProminent)
            .tint(MatchInkControlColors.actionBackground)
        } else {
          Button("New match", action: onNewMatch).buttonStyle(.bordered)
        }
      }
    }
  }
}
