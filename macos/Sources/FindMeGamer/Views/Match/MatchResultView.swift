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

  init(storedIDs: String = "") {
    selectedIDs = Set(storedIDs.split(separator: ",").compactMap { UUID(uuidString: String($0)) })
  }

  var storedIDs: String { selectedIDs.map(\.uuidString).sorted().joined(separator: ",") }

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
  var acceptedBatch: SendBatch? = nil
  var onViewCampaign: (UUID) -> Void = { _ in }

  @Environment(\.dismiss) private var dismiss
  @SceneStorage private var otherExpanded: Bool
  @SceneStorage private var storedSelection: String
  @State private var selection = MatchRecipientSelection()
  @State private var restoredSelection = false
  @State private var retainedResult: MatchResult?

  init(
    matchID: UUID, model: MatchModel, writesEnabled: Bool,
    onOpenProfile: @escaping (ProfileType, UUID) -> Void,
    onComposeOutreach: @escaping (UUID, [OutreachRecipientContext]) -> Void,
    onResendDelivery: @escaping (UUID) -> Void,
    acceptedBatch: SendBatch? = nil,
    onViewCampaign: @escaping (UUID) -> Void = { _ in }
  ) {
    self.matchID = matchID
    self.model = model
    self.writesEnabled = writesEnabled
    self.onOpenProfile = onOpenProfile
    self.onComposeOutreach = onComposeOutreach
    self.onResendDelivery = onResendDelivery
    self.acceptedBatch = acceptedBatch
    self.onViewCampaign = onViewCampaign
    _otherExpanded = SceneStorage(wrappedValue: false, "match.other.\(matchID.uuidString)")
    _storedSelection = SceneStorage(wrappedValue: "", "match.selection.\(matchID.uuidString)")
  }

  var body: some View {
    VStack(spacing: 0) {
      stateContent
    }
    .accessibilityIdentifier(MatchAccessibility.result)
    .navigationTitle("Match Result")
    .workspaceCanvas()
    .task(id: matchID) {
      selection = MatchRecipientSelection(storedIDs: storedSelection)
      restoredSelection = true
      await model.openResult(id: matchID)
    }
    .onChange(of: matchID) { _, _ in
      selection = MatchRecipientSelection()
      otherExpanded = false
      retainedResult = nil
      restoredSelection = false
    }
    .onChange(of: model.resultState, initial: true) { _, state in
      guard case .available(let result) = state, result.id == matchID else { return }
      retainedResult = result
      if restoredSelection { selection.reconcile(with: result) }
    }
    .onChange(of: selection) { _, selection in
      if restoredSelection { storedSelection = selection.storedIDs }
    }
  }

  @ViewBuilder private var stateContent: some View {
    if let result = displayedResult {
      availableContent(result)
    } else {
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
        ContentUnavailableView {
          Label(MatchCopy.noSuitableCreators, systemImage: "person.slash")
        } description: {
          Text(
            "No eligible creators were found for this game. Add more Creator Profiles in Library, or return to choose another game."
          )
        } actions: {
          Button("Back to matches") { dismiss() }
            .buttonStyle(.borderedProminent)
        }
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
      case .available:
        ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
  }

  private var displayedResult: MatchResult? {
    if case .available(let result) = model.resultState, result.id == matchID { return result }
    switch model.resultState {
    case .loading, .failed:
      return retainedResult?.id == matchID ? retainedResult : nil
    default: return nil
    }
  }

  private var canActOnResult: Bool {
    MatchResultInteractionPolicy.canAct(
      on: matchID, state: model.resultState, writesEnabled: writesEnabled)
  }

  private func availableContent(_ result: MatchResult) -> some View {
    let presentation = MatchResultPresentation(result: result)
    return VStack(spacing: 0) {
      if let batch = acceptedBatch, batch.matchTaskID == matchID {
        ViewThatFits(in: .horizontal) {
          HStack(spacing: 12) {
            acceptedSummary(batch)
            Spacer()
            Button("View campaign") { onViewCampaign(batch.campaignID) }
          }
          VStack(alignment: .leading, spacing: 8) {
            acceptedSummary(batch)
            Button("View campaign") { onViewCampaign(batch.campaignID) }
          }
        }
        .fixedSize(horizontal: false, vertical: true)
        .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
        .padding(.vertical, 12)
        .background(Color.accentColor.opacity(0.05))
      }
      ScrollView {
        LazyVStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
          gameHeader(
            result.game,
            creatorCount: presentation.recommended.count + presentation.other.count)

          if case .failed(let message) = model.resultState {
            HStack(spacing: 10) {
              Label(message, systemImage: "exclamationmark.triangle")
                .font(.callout)
                .foregroundStyle(.secondary)
              Button("Retry refresh") { Task { await model.openResult(id: matchID) } }
            }
          }

          VStack(alignment: .leading, spacing: 10) {
            WorkspaceSectionHeader(
              MatchCopy.recommended,
              subtitle: "Review the fit, then select creators to prepare outreach.",
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
        .frame(maxWidth: 1_040, alignment: .leading)
        .frame(maxWidth: .infinity)
      }

      BatchOutreachBar(
        selectedCount: selection.count, writesEnabled: canActOnResult,
        isRefreshing: model.resultState == .loading,
        onSend: {
          guard canActOnResult else { return }
          onComposeOutreach(result.id, selection.orderedRecipients(in: result))
        })
    }
  }

  private func acceptedSummary(_ batch: SendBatch) -> some View {
    let count = batch.requestedCreatorIDs.count
    return Label(
      "Outreach submitted · \(count) \(count == 1 ? "creator" : "creators")",
      systemImage: "checkmark.circle"
    )
    .font(.callout)
  }

  private func gameHeader(_ game: MatchGameHeader, creatorCount: Int) -> some View {
    HStack(alignment: .center, spacing: 18) {
      Button {
        onOpenProfile(.game, game.id)
      } label: {
        AsyncArtwork(
          url: ArtworkURLPolicy.validated(game.coverURL.flatMap(URL.init(string:))),
          fallbackSystemImage: "gamecontroller.fill"
        )
        .frame(width: 84, height: 76)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .rotationEffect(.degrees(-3))
        .shadow(color: .black.opacity(0.09), radius: 10, y: 4)
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open \(game.name) profile")
      VStack(alignment: .leading, spacing: 8) {
        Text("YOUR CREATOR SHORTLIST")
          .font(.system(size: 10, weight: .bold, design: .rounded))
          .tracking(1.5)
          .foregroundStyle(StudioPalette.blue)
        Button(game.name) { onOpenProfile(.game, game.id) }
          .buttonStyle(.plain)
          .font(.system(size: 27, weight: .semibold, design: .rounded))
          .tracking(-0.7)
          .fixedSize(horizontal: false, vertical: true)
          .accessibilityIdentifier(MatchAccessibility.gameProfile)
          .help("Open this Game Profile")
        Text("\(creatorCount) creators to explore. Find the voices you want to work with.")
          .font(.callout)
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
      }
      Spacer(minLength: 0)
    }
    .padding(.vertical, 6)
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
          writesEnabled: canActOnResult,
          onOpenProfile: { onOpenProfile(.creator, candidate.id) },
          onSend: {
            guard canActOnResult else { return }
            onComposeOutreach(
              result.id, [MatchRecipientSelection.recipientContext(candidate.source)])
          },
          onResend: { deliveryID in
            guard canActOnResult else { return }
            onResendDelivery(deliveryID)
          })
      }
    }
  }

  private func selectionBinding(for candidate: MatchCandidate) -> Binding<Bool> {
    Binding(
      get: { selection.contains(candidate.id) },
      set: { selected in
        guard canActOnResult, selected != selection.contains(candidate.id) else { return }
        selection.toggle(candidate)
      })
  }
}
