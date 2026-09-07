import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct WorkspaceAccessFeedbackTests {
  @Test func controlsReplaceOnlyTheExactNormalStateHints() {
    #expect(WorkspaceAccessFeedback.visibleMessage(state: .needsKey, message: "") == nil)
    #expect(WorkspaceAccessFeedback.visibleMessage(state: .needsKey, message: " \n ") == nil)
    #expect(
      WorkspaceAccessFeedback.visibleMessage(
        state: .needsKey, message: "Enter a Workspace Access Key to connect.") == nil)
    #expect(
      WorkspaceAccessFeedback.visibleMessage(
        state: .checking, message: "Checking workspace access…") == nil)
    #expect(
      WorkspaceAccessFeedback.visibleMessage(state: .authenticated, message: "Connected.") == nil)
  }

  @Test func failuresAndUnfamiliarMessagesRemainVerbatim() {
    for state in [AppSession.State.needsKey, .checking, .offline, .authenticated] {
      for message in [
        "The Workspace Access Key is invalid.",
        "The Workspace Access Key could not be saved on this Mac.",
        "The app configuration does not contain a valid API address.",
        "Workspace offline. Changes are unavailable.",
        "A future server message with a recovery action.",
      ] {
        #expect(WorkspaceAccessFeedback.visibleMessage(state: state, message: message) == message)
      }
    }
    #expect(
      WorkspaceAccessFeedback.visibleMessage(
        state: .offline, message: "Enter a Workspace Access Key to connect.")
        == "Enter a Workspace Access Key to connect.")
  }
}
