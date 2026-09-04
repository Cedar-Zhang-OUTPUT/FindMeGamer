import FindMeGamerCore
import SwiftUI

struct ProfileSheet: View {
  let onFavorite: ProfileFavoriteAction
  let onReanalyze: ProfileReanalyzeAction
  let onSaveManual: ProfileSaveManualAction
  let makeIdempotencyKey: @Sendable () -> String

  @Environment(\.dismiss) private var dismiss
  @Environment(\.workspaceWritesEnabled) private var writesEnabled
  @State private var state: ProfileSheetState

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
      WorkspaceSurface(style: .elevated) {
        ProfileHeader(
          profile: state.currentProfile,
          isFavorite: state.favorite,
          writesEnabled: writesEnabled,
          isFavoriteInFlight: state.isFavoriteInFlight,
          isReanalyzeInFlight: state.isReanalyzeInFlight,
          onFavorite: favorite,
          onReanalyze: reanalyze
        )
        .padding(WorkspaceDesign.spaceM)
      }

      if let message = state.actionMessage {
        Label(message, systemImage: "exclamationmark.triangle")
          .foregroundStyle(.red)
          .textSelection(.enabled)
      }

      ScrollView {
        detail
          .padding(.vertical, 2)
          .frame(maxWidth: 1_020, alignment: .leading)
          .frame(maxWidth: .infinity)
      }

      HStack {
        Spacer()
        Button("Close") { dismiss() }
          .keyboardShortcut(.cancelAction)
          .accessibilityIdentifier("profile.close")
      }
    }
    .padding(WorkspaceDesign.spaceL)
    .frame(minWidth: 700, idealWidth: 920, minHeight: 560)
    .workspaceCanvas()
    .accessibilityIdentifier("profile.sheet")
  }

  @ViewBuilder private var detail: some View {
    switch state.currentProfile {
    case .game(let game):
      GameProfileDetail(profile: game)
    case .creator(let creator):
      CreatorProfileDetail(
        presentation: CreatorProfilePresentation(profile: creator),
        manualDraft: $state.manualDraft,
        writesEnabled: writesEnabled,
        isSaving: state.isManualSaveInFlight,
        onSave: saveManual)
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
