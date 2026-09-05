import FindMeGamerCore
import SwiftUI

enum MatchHistorySemantic: Equatable {
  case progress(String)
  case succeeded(resultCount: Int)
  case failed(String)
  case superseded
}

struct MatchHistoryPresentation: Equatable {
  let semantic: MatchHistorySemantic
  let canOpenResult: Bool
  let showsRetry: Bool
  let canRetry: Bool

  init(task: MatchTask, modelCanRetry: Bool, writesEnabled: Bool) {
    canOpenResult = task.status == .succeeded
    showsRetry = task.status == .failed && task.retryable
    canRetry = showsRetry && modelCanRetry && writesEnabled
    switch task.status {
    case .queued: semantic = .progress("Queued")
    case .running: semantic = .progress(task.stage.matchWorkflowLabel)
    case .succeeded: semantic = .succeeded(resultCount: task.resultCount)
    case .failed: semantic = .failed(task.failure?.message ?? "Match failed.")
    case .superseded: semantic = .superseded
    }
  }
}

struct MatchHistoryList: View {
  @Bindable var model: MatchModel
  let writesEnabled: Bool
  let focusedTaskID: UUID?
  let onFocusTask: (UUID) -> Void
  @SceneStorage("match.historyExpanded") private var expanded = false

  private var history: MatchHistoryVisibility {
    MatchHistoryVisibility(tasks: model.tasks, focusedTaskID: focusedTaskID, expanded: expanded)
  }

  var body: some View {
    if history.totalCount > 0 || model.isLoadingHistory || model.historyError != nil {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      HStack(spacing: 8) {
        Text("Recent matches").font(.headline)
        Text("\(history.totalCount)").font(.caption).foregroundStyle(.secondary)
        Spacer()
        if model.isLoadingHistory {
          ProgressView().controlSize(.small)
            .accessibilityLabel("Loading Match history")
        }
        if history.totalCount > 3 {
          Button(expanded ? "Show recent" : "Show all \(history.totalCount)") { expanded.toggle() }
            .buttonStyle(.plain)
            .font(.callout)
            .foregroundStyle(Color.accentColor)
        }
      }
      if let historyError = model.historyError {
        HStack(spacing: 8) {
          Label(historyError, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.secondary)
          Button("Try Again") { Task { await model.loadHistory() } }
        }
        .controlSize(.small)
      }
      if !history.visible.isEmpty {
        LazyVStack(spacing: 0) {
          ForEach(history.visible) { task in
            MatchHistoryRow(
              model: model, task: task, writesEnabled: writesEnabled,
              onFocus: { onFocusTask(task.id) })
            if task.id != history.visible.last?.id { Divider() }
          }
        }
      }
    }
    .accessibilityIdentifier(MatchAccessibility.history)
    }
  }
}

private struct MatchHistoryRow: View {
  @Bindable var model: MatchModel
  let task: MatchTask
  let writesEnabled: Bool
  let onFocus: () -> Void

  private var presentation: MatchHistoryPresentation {
    MatchHistoryPresentation(
      task: task, modelCanRetry: model.canRetry(task: task), writesEnabled: writesEnabled)
  }

  var body: some View {
    HStack(spacing: 12) {
      AsyncArtwork(
        url: ArtworkURLPolicy.validated(task.game.coverURL.flatMap(URL.init(string:))),
        fallbackSystemImage: "gamecontroller.fill"
      )
      .frame(width: 44, height: 36)
      .clipShape(RoundedRectangle(cornerRadius: 7))
      VStack(alignment: .leading, spacing: 5) {
        Text(task.game.name).font(.body.weight(.medium))
        ViewThatFits(in: .horizontal) {
          HStack(spacing: 8) {
            status
            timestamp
          }
          VStack(alignment: .leading, spacing: 4) {
            status
            timestamp
          }
        }
      }
      Spacer(minLength: 8)
      if presentation.canOpenResult {
        NavigationLink("Review", value: MatchRoute.result(task.id))
          .buttonStyle(.borderless)
      } else {
        Button(task.status == .failed ? "View issue" : "View status", action: onFocus)
          .buttonStyle(.borderless)
      }
    }
    .padding(.vertical, 14)
    .accessibilityIdentifier(MatchAccessibility.task(task.id))
  }

  private var timestamp: some View {
    Text(task.createdAt, style: .relative)
      .font(.caption)
      .foregroundStyle(.secondary)
      .accessibilityLabel("Created \(task.createdAt.formatted())")
  }

  @ViewBuilder private var status: some View {
    switch presentation.semantic {
    case .progress(let label):
      HStack(spacing: 6) {
        ProgressView().controlSize(.mini)
        Text(label)
      }
      .font(.caption)
      .foregroundStyle(.secondary)
    case .succeeded(let count):
      Text("\(count) creators").font(.caption).foregroundStyle(.secondary)
    case .failed:
      Label("Failed", systemImage: "exclamationmark.circle")
        .font(.caption)
        .foregroundStyle(.red)
    case .superseded:
      Text("Replaced by a newer match").font(.caption).foregroundStyle(.secondary)
    }
  }
}
