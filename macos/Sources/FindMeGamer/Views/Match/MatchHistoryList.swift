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
    case .queued:
      semantic = .progress("Queued")
    case .running:
      semantic = .progress(task.stage.matchWorkflowLabel)
    case .succeeded:
      semantic = .succeeded(resultCount: task.resultCount)
    case .failed:
      semantic = .failed(task.failure?.message ?? "Match failed.")
    case .superseded:
      semantic = .superseded
    }
  }
}

struct MatchHistoryList: View {
  @Bindable var model: MatchModel
  let writesEnabled: Bool

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Text(MatchCopy.history)
          .font(.title2.bold())
        Spacer()
        if model.isLoadingHistory {
          ProgressView()
            .controlSize(.small)
        }
      }

      if let historyError = model.historyError {
        HStack(spacing: 8) {
          Label(historyError, systemImage: "exclamationmark.triangle")
            .foregroundStyle(.secondary)
          Button("Try Again") {
            Task { await model.loadHistory() }
          }
        }
        .controlSize(.small)
      }

      if model.tasks.isEmpty && !model.isLoadingHistory {
        ContentUnavailableView(
          "No Match history", systemImage: "person.2.badge.magnifyingglass",
          description: Text("Completed and active Match tasks will appear here."))
      } else {
        List(model.tasks) { task in
          MatchHistoryRow(model: model, task: task, writesEnabled: writesEnabled)
        }
        .listStyle(.inset)
      }
    }
    .padding(.horizontal, 20)
    .padding(.vertical, 16)
    .frame(maxHeight: .infinity)
    .accessibilityIdentifier(MatchAccessibility.history)
  }
}

private struct MatchHistoryRow: View {
  @Bindable var model: MatchModel
  let task: MatchTask
  let writesEnabled: Bool

  private var presentation: MatchHistoryPresentation {
    MatchHistoryPresentation(
      task: task, modelCanRetry: model.canRetry(task: task), writesEnabled: writesEnabled)
  }

  var body: some View {
    Group {
      if presentation.canOpenResult {
        NavigationLink(value: MatchRoute.result(task.id)) {
          rowContent
        }
      } else {
        rowContent
      }
    }
    .accessibilityIdentifier(MatchAccessibility.task(task.id))
  }

  private var rowContent: some View {
    HStack(alignment: .top, spacing: 12) {
      AsyncArtwork(
        url: ArtworkURLPolicy.validated(task.game.coverURL.flatMap(URL.init(string:))),
        fallbackSystemImage: "gamecontroller"
      )
      .frame(width: 54, height: 54)
      .clipShape(RoundedRectangle(cornerRadius: 8))

      VStack(alignment: .leading, spacing: 5) {
        HStack(alignment: .firstTextBaseline) {
          Text(task.game.name)
            .font(.headline)
          Spacer()
          Text(task.createdAt, style: .relative)
            .font(.caption)
            .foregroundStyle(.secondary)
            .accessibilityLabel("Created \(task.createdAt.formatted())")
        }

        Text(task.stage.matchWorkflowLabel)
          .font(.caption)
          .foregroundStyle(.secondary)

        status

        if presentation.showsRetry {
          Button("Retry") {
            Task { await model.retry(task: task) }
          }
          .controlSize(.small)
          .disabled(!presentation.canRetry)
          .help("Retry this failed Match")
        }
      }
    }
    .padding(.vertical, 6)
  }

  @ViewBuilder private var status: some View {
    switch presentation.semantic {
    case .progress(let label):
      HStack(spacing: 7) {
        ProgressView()
          .controlSize(.small)
        Text(label)
      }
    case .succeeded(let resultCount):
      Label("Completed · \(resultCount) creators", systemImage: "checkmark.circle.fill")
        .foregroundStyle(.green)
    case .failed(let message):
      VStack(alignment: .leading, spacing: 3) {
        Label("Failed", systemImage: "xmark.circle.fill")
          .foregroundStyle(.red)
        Text(message)
          .font(.caption)
          .foregroundStyle(.secondary)
          .textSelection(.enabled)
      }
    case .superseded:
      Label("Superseded", systemImage: "arrow.trianglehead.2.clockwise.rotate.90")
        .foregroundStyle(.secondary)
    }
  }
}
