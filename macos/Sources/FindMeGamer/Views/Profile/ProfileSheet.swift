import FindMeGamerCore
import SwiftUI

struct ProfileSheet: View {
  let onFavorite: ProfileFavoriteAction
  let onReanalyze: ProfileReanalyzeAction
  let onSaveManual: ProfileSaveManualAction
  let makeIdempotencyKey: @Sendable () -> String

  @Environment(\.dismiss) private var dismiss
  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var state: ProfileSheetState
  @State private var destination: ProfileDetailDestination = .overview
  @State private var isConfirmingDiscard = false

  init(
    profile: Profile,
    onFavorite: @escaping ProfileFavoriteAction,
    onReanalyze: @escaping ProfileReanalyzeAction,
    onSaveManual: @escaping ProfileSaveManualAction,
    makeIdempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString }
  ) {
    self.onFavorite = onFavorite
    self.onReanalyze = onReanalyze
    self.onSaveManual = onSaveManual
    self.makeIdempotencyKey = makeIdempotencyKey
    _state = State(initialValue: ProfileSheetState(profile: profile))
  }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      ProfileHeader(
        profile: state.currentProfile,
        isFavorite: state.favorite,
        writesEnabled: writesEnabled,
        isFavoriteInFlight: state.isFavoriteInFlight,
        isReanalyzeInFlight: state.isReanalyzeInFlight,
        onFavorite: favorite,
        onReanalyze: reanalyze,
        isCompact: destination != .overview
      )

      StudioSectionTabs(
        title: "Profile section",
        options: ProfileDetailDestination.available(for: profileType),
        selection: $destination,
        label: { $0.title }
      )
      .frame(maxWidth: 530)
      .accessibilityIdentifier("profile.section")

      if !writesEnabled {
        Label(
          "Offline — profiles remain readable. Reconnect to save changes.",
          systemImage: "wifi.slash"
        )
        .font(.subheadline)
        .foregroundStyle(.secondary)
      }

      if let warning = staleWarning, destination != .overview {
        Label(warning, systemImage: "exclamationmark.triangle.fill")
          .foregroundStyle(.orange)
          .font(.subheadline)
      }

      if let message = state.actionMessage {
        Label(message, systemImage: "exclamationmark.triangle")
          .foregroundStyle(.red)
          .textSelection(.enabled)
      }

      ScrollViewReader { scrollProxy in
        ScrollView {
          VStack(alignment: .leading, spacing: 0) {
            Color.clear
              .frame(height: 0)
              .id(ProfileScrollAnchor.top)
              .accessibilityHidden(true)

            detail
              .padding(.vertical, 2)
              .frame(maxWidth: 1_020, alignment: .leading)
              .frame(maxWidth: .infinity)
          }
        }
        .onChange(of: destination) { _, _ in
          // Section selection is an explicit navigation action. Keep the same
          // editor/model instances, but don't inherit another section's offset.
          // Profile refreshes and draft edits never enter this path.
          var transaction = Transaction(animation: nil)
          transaction.disablesAnimations = true
          withTransaction(transaction) {
            scrollProxy.scrollTo(ProfileScrollAnchor.top, anchor: .top)
          }
        }
      }

      HStack {
        if let success = state.actionSuccessMessage {
          Label(success, systemImage: "checkmark.circle")
            .font(.caption)
            .foregroundStyle(.secondary)
            .accessibilityIdentifier("profile.actionSuccess")
        }
        if state.hasUnsavedManualChanges {
          Text("Unsaved contact or notes")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        Spacer()
        Button("Close") { requestClose() }
          .disabled(state.isManualSaveInFlight)
          .keyboardShortcut(.cancelAction)
          .accessibilityIdentifier("profile.close")
      }
    }
    .padding(WorkspaceDesign.spaceL)
    .frame(minWidth: 620, idealWidth: 940, minHeight: 620, idealHeight: 780)
    .tint(StudioPalette.blue)
    .workspaceCanvas()
    .accessibilityIdentifier("profile.sheet")
    .interactiveDismissDisabled(state.hasUnsavedManualChanges || state.isManualSaveInFlight)
    .confirmationDialog(
      "Discard unsaved contact changes?", isPresented: $isConfirmingDiscard,
      titleVisibility: .visible
    ) {
      Button("Discard Changes", role: .destructive) { dismiss() }
      Button("Keep Editing", role: .cancel) { destination = .contacts }
    } message: {
      Text("Your saved profile is unchanged. Contact and note edits in this window will be lost.")
    }
  }

  @ViewBuilder private var detail: some View {
    switch state.currentProfile {
    case .game(let game):
      GameProfileDetail(profile: game, destination: destination)
    case .creator(let creator):
      CreatorProfileDetail(
        presentation: CreatorProfilePresentation(profile: creator),
        manualDraft: $state.manualDraft,
        writesEnabled: writesEnabled,
        isSaving: state.isManualSaveInFlight,
        onSave: saveManual,
        destination: destination,
        hasUnsavedChanges: state.hasUnsavedManualChanges,
        manualEditorMode: state.manualEditorMode,
        onEditManual: state.beginManualEditing,
        onDiscardManual: state.discardManualEditing,
        onReanalyze: reanalyze,
        isReanalyzing: state.isReanalyzeInFlight,
        onOpenContacts: { destination = .contacts })
    }
  }

  private var profileType: ProfileType {
    switch state.currentProfile {
    case .game: .game
    case .creator: .creator
    }
  }

  private var staleWarning: String? {
    guard case .creator(let creator) = state.currentProfile else { return nil }
    return CreatorProfilePresentation(profile: creator).staleWarning
  }

  private func requestClose() {
    guard !state.isManualSaveInFlight else { return }
    if state.hasUnsavedManualChanges {
      isConfirmingDiscard = true
    } else {
      dismiss()
    }
  }

  private func favorite() {
    Task { await state.toggleFavorite(using: onFavorite) }
  }

  private func reanalyze() {
    let idempotencyKey = makeIdempotencyKey()
    Task { await state.reanalyze(idempotencyKey: idempotencyKey, using: onReanalyze) }
  }

  private func saveManual() {
    Task { await state.saveManual(using: onSaveManual) }
  }
}

private enum ProfileScrollAnchor: Hashable {
  case top
}

extension ProfileSheet {
  @MainActor
  static func preview(profile: Profile) -> ProfileSheet {
    ProfileSheet(
      profile: profile,
      onFavorite: { _, _, _ in throw CancellationError() },
      onReanalyze: { _, _, _ in throw CancellationError() },
      onSaveManual: { _, _, _ in throw CancellationError() })
  }
}
