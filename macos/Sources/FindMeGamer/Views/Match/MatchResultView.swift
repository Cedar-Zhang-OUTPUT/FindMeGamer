import FindMeGamerCore
import SwiftUI

struct MatchResultPresentation: Equatable {
  let recommended: [MatchCandidatePresentation]
  let other: [MatchCandidatePresentation]

  init(result: MatchResult) {
    recommended = result.recommendedMatches.map(MatchCandidatePresentation.init(candidate:))
    other = result.otherMatches.map(MatchCandidatePresentation.init(candidate:))
  }
}

struct MatchRecipientSelection: Equatable {
  private var selectedIDs: Set<UUID> = []

  var count: Int { selectedIDs.count }
  var isEmpty: Bool { selectedIDs.isEmpty }

  func contains(_ id: UUID) -> Bool { selectedIDs.contains(id) }

  mutating func toggle(_ candidate: MatchCandidate) {
    guard MatchOutreachActionPolicy.isEligibleForNewSend(candidate) else { return }
    if selectedIDs.contains(candidate.id) {
      selectedIDs.remove(candidate.id)
    } else {
      selectedIDs.insert(candidate.id)
    }
  }

  mutating func reconcile(with result: MatchResult) {
    let eligible = Set(
      (result.recommendedMatches + result.otherMatches)
        .filter(MatchOutreachActionPolicy.isEligibleForNewSend)
        .map(\.id))
    selectedIDs.formIntersection(eligible)
  }

  func orderedIDs(in result: MatchResult) -> [UUID] {
    var seen = Set<UUID>()
    var ordered: [UUID] = []
    for candidate in result.recommendedMatches + result.otherMatches
    where selectedIDs.contains(candidate.id) && seen.insert(candidate.id).inserted {
      ordered.append(candidate.id)
    }
    return ordered
  }
}

struct MatchResultView: View {
  let matchID: UUID
  @Bindable var model: MatchModel
  let writesEnabled: Bool
  let onOpenProfile: (ProfileType, UUID) -> Void
  let onComposeOutreach: (UUID, [UUID]) -> Void
  let onResendDelivery: (UUID) -> Void

  @State private var otherExpanded = false
  @State private var selection = MatchRecipientSelection()

  var body: some View {
    VStack(spacing: 0) {
      stateContent
    }
    .accessibilityIdentifier(MatchAccessibility.result)
    .navigationTitle("Match Result")
    .task(id: matchID) {
      await model.openResult(id: matchID)
    }
    .onChange(of: matchID) { _, _ in
      selection = MatchRecipientSelection()
      otherExpanded = false
    }
    .onChange(of: model.resultState, initial: true) { _, state in
      guard case .available(let result) = state, result.id == matchID else { return }
      selection.reconcile(with: result)
    }
  }

  @ViewBuilder private var stateContent: some View {
    switch model.resultState {
    case .idle:
      ContentUnavailableView(
        "Match result", systemImage: "person.2.badge.magnifyingglass",
        description: Text("Loading Match details…"))
    case .loading:
      VStack(spacing: 10) {
        ProgressView()
        Text("Loading Match result…")
          .foregroundStyle(.secondary)
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    case .empty:
      ContentUnavailableView(
        MatchCopy.noSuitableCreators, systemImage: "person.slash",
        description: Text("This Match completed without eligible Creator results."))
    case .failed(let message):
      VStack(spacing: 12) {
        Label(message, systemImage: "exclamationmark.triangle")
          .foregroundStyle(.red)
          .textSelection(.enabled)
        Button("Try Again") {
          Task { await model.openResult(id: matchID) }
        }
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    case .available(let result):
      if result.id == matchID {
        availableContent(result)
      } else {
        ProgressView()
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
  }

  private func availableContent(_ result: MatchResult) -> some View {
    let presentation = MatchResultPresentation(result: result)
    return VStack(spacing: 0) {
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 18) {
          gameHeader(result.game)

          VStack(alignment: .leading, spacing: 10) {
            Text(MatchCopy.recommended)
              .font(.title2.bold())
            candidateGroup(
              presentation.recommended, result: result,
              emptyCopy: "No recommended Creators in this Match.")
          }

          DisclosureGroup(isExpanded: $otherExpanded) {
            candidateGroup(
              presentation.other, result: result,
              emptyCopy: "No other Creators in this Match."
            )
            .padding(.top, 10)
          } label: {
            Text(MatchCopy.other)
              .font(.title3.weight(.semibold))
          }
        }
        .padding(20)
      }

      BatchOutreachBar(
        selectedCount: selection.count, writesEnabled: writesEnabled,
        onSend: {
          onComposeOutreach(result.id, selection.orderedIDs(in: result))
        })
    }
  }

  private func gameHeader(_ game: MatchGameHeader) -> some View {
    HStack(spacing: 12) {
      AsyncArtwork(
        url: ArtworkURLPolicy.validated(game.coverURL.flatMap(URL.init(string:))),
        fallbackSystemImage: "gamecontroller"
      )
      .frame(width: 72, height: 72)
      .clipShape(RoundedRectangle(cornerRadius: 9))

      VStack(alignment: .leading, spacing: 5) {
        Text("Matched for")
          .font(.caption)
          .foregroundStyle(.secondary)
        Button(game.name) { onOpenProfile(.game, game.id) }
          .buttonStyle(.link)
          .font(.title2.weight(.semibold))
          .accessibilityIdentifier(MatchAccessibility.gameProfile)
          .help("Open this Game Profile")
      }
      Spacer()
    }
  }

  @ViewBuilder
  private func candidateGroup(
    _ candidates: [MatchCandidatePresentation],
    result: MatchResult,
    emptyCopy: String
  ) -> some View {
    if candidates.isEmpty {
      Text(emptyCopy)
        .font(.body)
        .foregroundStyle(.secondary)
    } else {
      ForEach(candidates) { candidate in
        CreatorMatchRow(
          presentation: candidate,
          isSelected: selectionBinding(for: candidate.source),
          writesEnabled: writesEnabled,
          onOpenProfile: { onOpenProfile(.creator, candidate.id) },
          onSend: { onComposeOutreach(result.id, [candidate.id]) },
          onResend: onResendDelivery)
      }
    }
  }

  private func selectionBinding(for candidate: MatchCandidate) -> Binding<Bool> {
    Binding(
      get: { selection.contains(candidate.id) },
      set: { selected in
        guard selected != selection.contains(candidate.id) else { return }
        selection.toggle(candidate)
      })
  }
}
