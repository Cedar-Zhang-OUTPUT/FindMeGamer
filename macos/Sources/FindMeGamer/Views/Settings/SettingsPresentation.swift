import FindMeGamerCore
import Observation

/// Observable presentation shared by the adaptive form and its extracted sections.
/// Section actions must invalidate their own content without waiting for a
/// category switch or a window resize to rebuild the parent geometry.
@MainActor @Observable final class SettingsPresentation {
  var expandedConnection: ConnectionService?
  var replacementConfirmation: ConnectionService?
  var isShowingSaveConfirmation = false
  var isShowingActivity = false
  var isShowingDisconnectConfirmation = false
  var isShowingConnectionDetails = false
}
