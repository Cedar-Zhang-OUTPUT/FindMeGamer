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
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      HStack {
        WorkspaceSectionHeader(
          MatchCopy.history,
          subtitle: "Active work and recent results, newest first.",
          count: model.tasks.count)
        Spacer()
        if model.isLoadingHistory {
          ProgressView()
            .controlSize(.small)
            .accessibilityLabel("Loading Match history")
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
        ScrollView {
          LazyVStack(spacing: WorkspaceDesign.spaceS) {
            ForEach(model.tasks) { task in
              MatchHistoryRow(model: model, task: task, writesEnabled: writesEnabled)
            }
          }
          .padding(.vertical, 1)
        }
      }
    }
    .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
    .padding(.top, WorkspaceDesign.spaceL)
    .padding(.bottom, WorkspaceDesign.pageVerticalPadding)
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
    .buttonStyle(.plain)
    .accessibilityIdentifier(MatchAccessibility.task(task.id))
  }

  private var rowContent: some View {
    WorkspaceSurface(style: .card) {
      HStack(alignment: .center, spacing: WorkspaceDesign.spaceM) {
        Capsule()
          .fill(statusColor)
          .frame(width: 3, height: 48)
          .accessibilityHidden(true)

        AsyncArtwork(
          url: ArtworkURLPolicy.validated(task.game.coverURL.flatMap(URL.init(string:))),
          fallbackSystemImage: "gamecontroller.fill"
        )
        .frame(width: 58, height: 58)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

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
        }

        if presentation.showsRetry {
          Button("Retry") {
            Task { await model.retry(task: task) }
          }
          .controlSize(.small)
          .disabled(!presentation.canRetry)
          .help("Retry this failed Match")
        }
      }
      .padding(WorkspaceDesign.spaceS)
    }
  }

  private var statusColor: Color {
    switch presentation.semantic {
    case .progress: .accentColor
    case .succeeded: .green
    case .failed: .red
    case .superseded: .secondary
    }
  }

  @ViewBuilder private var status: some View {
    switch presentation.semantic {
    case .progress(let label):
      HStack(spacing: 7) {
        ProgressView()
          .controlSize(.small)
        Text(label)
      }
      .font(.caption.weight(.medium))
    case .succeeded(let resultCount):
      WorkspaceStatusLozenge(
        title: "Completed · \(resultCount) creators",
        systemImage: "checkmark.circle.fill",
        tone: .success)
    case .failed(let message):
      VStack(alignment: .leading, spacing: 3) {
        WorkspaceStatusLozenge(
          title: "Failed",
          systemImage: "xmark.circle.fill",
          tone: .danger)
        Text(message)
          .font(.caption)
          .foregroundStyle(.secondary)
          .textSelection(.enabled)
      }
    case .superseded:
      WorkspaceStatusLozenge(
        title: "Superseded",
        systemImage: "arrow.trianglehead.2.clockwise.rotate.90",
        tone: .neutral)
    }
  }
}
