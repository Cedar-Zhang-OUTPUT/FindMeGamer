import Testing

@testable import FindMeGamer

@Suite struct OutreachJourneyTests {
  @Test func ambiguousRecipientsStartAtAddressSelection() {
    #expect(OutreachComposerStage.initial(unresolvedRecipients: 2) == .recipients)
    #expect(OutreachComposerStage.initial(unresolvedRecipients: 0) == .message)
  }

  @Test func reviewRequiresAddressesAndANonemptyMessage() {
    #expect(
      !OutreachComposerStage.canReview(unresolvedRecipients: 1, subject: "Hello", body: "A message")
    )
    #expect(
      !OutreachComposerStage.canReview(unresolvedRecipients: 0, subject: " \n", body: "A message"))
    #expect(!OutreachComposerStage.canReview(unresolvedRecipients: 0, subject: "Hello", body: "\n"))
    #expect(
      OutreachComposerStage.canReview(unresolvedRecipients: 0, subject: "Hello", body: "A message"))
  }

  @Test func backNavigationKeepsThePreviousTaskDiscoverable() {
    #expect(OutreachComposerStage.recipients.previous == nil)
    #expect(OutreachComposerStage.message.previous == .recipients)
    #expect(OutreachComposerStage.review.previous == .message)
  }
}
