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

  func orderedRecipients(in result: MatchResult) -> [OutreachRecipientContext] {
    var seen = Set<UUID>()
    var ordered: [OutreachRecipientContext] = []
    for candidate in result.recommendedMatches + result.otherMatches
    where selectedIDs.contains(candidate.id) && seen.insert(candidate.id).inserted {
      ordered.append(Self.recipientContext(candidate))
    }
    return ordered
  }

  static func recipientContext(_ candidate: MatchCandidate) -> OutreachRecipientContext {
    OutreachRecipientContext(
      creatorID: candidate.creator.id,
      creatorName: candidate.creator.name,
      contacts: candidate.creator.contacts.map {
        OutreachRecipientContact(
          email: $0.email,
          purpose: $0.purpose,
          source: $0.source,
          sourceURL: $0.sourceURL,
          validationState: $0.validationState)
      })
  }
}

struct MatchResultView: View {
  let matchID: UUID
  @Bindable var model: MatchModel
  let writesEnabled: Bool
  let onOpenProfile: (ProfileType, UUID) -> Void
  let onComposeOutreach: (UUID, [OutreachRecipientContext]) -> Void
  let onResendDelivery: (UUID) -> Void

  @State private var otherExpanded = false
  @State private var selection = MatchRecipientSelection()

  var body: some View {
    VStack(spacing: 0) {
      stateContent
    }
    .accessibilityIdentifier(MatchAccessibility.result)
    .navigationTitle("Match Result")
    .workspaceCanvas()
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
        LazyVStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
          gameHeader(
            result.game,
            creatorCount: presentation.recommended.count + presentation.other.count)

          VStack(alignment: .leading, spacing: 10) {
            WorkspaceSectionHeader(
              MatchCopy.recommended,
              subtitle: "The clearest creator fits, ordered by the matching service.",
              count: presentation.recommended.count)
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
            WorkspaceSectionHeader(
              MatchCopy.other,
              subtitle: "Useful alternatives with weaker or mixed evidence.",
              count: presentation.other.count)
          }
        }
        .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
        .padding(.vertical, WorkspaceDesign.pageVerticalPadding)
        .frame(maxWidth: 1_120, alignment: .leading)
        .frame(maxWidth: .infinity)
      }

      BatchOutreachBar(
        selectedCount: selection.count, writesEnabled: writesEnabled,
        onSend: {
          onComposeOutreach(result.id, selection.orderedRecipients(in: result))
        })
    }
  }

  private func gameHeader(_ game: MatchGameHeader, creatorCount: Int) -> some View {
    WorkspaceSurface(style: .elevated) {
      HStack(spacing: WorkspaceDesign.spaceM) {
        AsyncArtwork(
          url: ArtworkURLPolicy.validated(game.coverURL.flatMap(URL.init(string:))),
          fallbackSystemImage: "gamecontroller.fill"
        )
        .frame(width: 116, height: 82)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

        VStack(alignment: .leading, spacing: 6) {
          Text("MATCH CONTEXT")
            .font(.caption2.weight(.bold))
            .tracking(1.3)
            .foregroundStyle(Color.accentColor)
          Button(game.name) { onOpenProfile(.game, game.id) }
            .buttonStyle(.plain)
            .font(.system(.title2, design: .serif, weight: .semibold))
            .accessibilityIdentifier(MatchAccessibility.gameProfile)
            .help("Open this Game Profile")
          Label("Open the full Game Profile", systemImage: "arrow.up.right")
            .font(.caption)
            .foregroundStyle(.secondary)
        }

        Spacer()

        WorkspaceStatusLozenge(
          title: "\(creatorCount) creators considered",
          systemImage: "person.2.fill",
          tone: .accent)
      }
      .padding(WorkspaceDesign.spaceM)
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
          onSend: {
            onComposeOutreach(
              result.id, [MatchRecipientSelection.recipientContext(candidate.source)])
          },
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
