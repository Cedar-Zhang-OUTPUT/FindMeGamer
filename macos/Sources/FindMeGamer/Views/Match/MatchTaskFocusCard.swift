import FindMeGamerCore
import SwiftUI

struct MatchTaskFocusCard: View {
  @Bindable var model: MatchModel
  let task: MatchTask
  let writesEnabled: Bool
  let onOpenGame: () -> Void

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
        VStack(alignment: .leading, spacing: 5) {
          Text("MADE FOR YOUR GAME")
            .font(.system(size: 10, weight: .bold, design: .rounded))
            .tracking(1.6)
            .foregroundStyle(Color(red: 0.61, green: 0.92, blue: 0.81))
          Button(action: onOpenGame) {
            Text(task.game.name)
              .font(.headline)
              .foregroundStyle(.white)
          }
          .buttonStyle(.plain)
          .help("Review the Game Profile used for this match")
        }
        Spacer(minLength: 0)
      }
      ViewThatFits(in: .horizontal) {
        HStack(alignment: .center, spacing: 32) {
          taskState.frame(minWidth: 280, maxWidth: .infinity, alignment: .leading)
          stateArtwork
        }
        taskState
      }
      if let message = model.actionError {
        Label(message, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(Color(red: 1, green: 0.72, blue: 0.66))
          .textSelection(.enabled)
      }
    }
    .padding(28)
    .frame(maxWidth: .infinity, minHeight: 240, alignment: .topLeading)
    .modifier(MatchInkSurface())
    .accessibilityIdentifier("match.focused-task")
  }

  @ViewBuilder private var stateArtwork: some View {
    if case .succeeded(let count) = presentation.semantic, count > 0 {
      VStack(spacing: 3) {
        Text(count, format: .number)
          .font(.system(size: 70, weight: .light, design: .rounded))
          .tracking(-3)
        Text(count == 1 ? "CREATOR TO EXPLORE" : "CREATORS TO EXPLORE")
          .font(.system(size: 9, weight: .semibold, design: .rounded))
          .tracking(1.1)
      }
      .foregroundStyle(Color(red: 0.61, green: 0.92, blue: 0.81))
      .frame(width: 185, height: 150)
      .background {
        Circle().strokeBorder(Color.white.opacity(0.08), lineWidth: 1)
          .frame(width: 150, height: 150)
      }
      .accessibilityHidden(true)
    } else if case .progress = presentation.semantic {
      MatchConnectionArtwork()
    }
  }

  @ViewBuilder private var taskState: some View {
    switch presentation.semantic {
    case .progress(let stage):
      VStack(alignment: .leading, spacing: 12) {
        Text("Connecting the dots.")
          .font(.system(size: 30, weight: .semibold, design: .rounded)).tracking(-0.8)
        HStack(spacing: 9) {
          ProgressView().controlSize(.small)
          Text(stage).font(.body.weight(.medium))
        }
        Text("You can leave this page or start another match. This task will keep running here.")
          .font(.callout)
          .foregroundStyle(Color.white.opacity(0.72))
          .fixedSize(horizontal: false, vertical: true)
      }
    case .succeeded(let count):
      VStack(alignment: .leading, spacing: 12) {
        Text(count > 0 ? "Your creator shortlist is ready" : "No suitable creators this time")
          .font(.system(size: 29, weight: .semibold, design: .rounded)).tracking(-0.8)
        Text(
          count > 0
            ? "Review \(count) creators, compare the evidence, then choose who to contact."
            : "Review the game context or add more Creator Profiles to your library before trying a new match."
        )
        .font(.callout)
        .foregroundStyle(Color.white.opacity(0.72))
        .fixedSize(horizontal: false, vertical: true)
        NavigationLink(value: MatchRoute.result(task.id)) {
          Label(count > 0 ? "Review creators" : "Review match", systemImage: "arrow.right")
            .foregroundStyle(.white)
        }
        .buttonStyle(.borderedProminent)
        .tint(MatchInkControlColors.actionBackground)
        .controlSize(.large)
      }
    case .failed(let message):
      VStack(alignment: .leading, spacing: 12) {
        Label("This match needs attention", systemImage: "exclamationmark.triangle")
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
          Text("Your game selection is preserved. Use New match to try again.")
            .font(.caption)
            .foregroundStyle(Color.white.opacity(0.72))
        }
      }
    case .superseded:
      VStack(alignment: .leading, spacing: 10) {
        Text("A newer match replaced this task").font(.title2.weight(.semibold))
        Text("Open the latest match in your recent history below, or start a new one.")
          .foregroundStyle(Color.white.opacity(0.72))
      }
    }
  }
}
