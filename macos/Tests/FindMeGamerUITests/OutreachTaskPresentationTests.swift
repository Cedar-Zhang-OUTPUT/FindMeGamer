import FindMeGamerCore
import Foundation
import Testing

@testable import FindMeGamer

@Suite struct OutreachTaskPresentationTests {
  @Test func previewNavigationUsesOnlyActualPreviewsAndStopsAtBothEnds() {
    let ids = [UUID(), UUID(), UUID()]
    let first = OutreachPreviewNavigation(ids: ids, selectedID: ids[0])
    #expect(first.previousID == nil)
    #expect(first.nextID == ids[1])
    #expect(first.position == "1 of 3")
    let middle = OutreachPreviewNavigation(ids: ids, selectedID: ids[1])
    #expect(middle.previousID == ids[0])
    #expect(middle.nextID == ids[2])
    #expect(middle.position == "2 of 3")
    let last = OutreachPreviewNavigation(ids: ids, selectedID: ids[2])
    #expect(last.previousID == ids[1])
    #expect(last.nextID == nil)
    #expect(last.position == "3 of 3")
  }

  @Test func missingPreviewDoesNotChooseOrInventAnotherRecipient() {
    for selection in [nil, UUID()] {
      let navigation = OutreachPreviewNavigation(ids: [UUID()], selectedID: selection)
      #expect(navigation.index == nil)
      #expect(navigation.nextID == nil && navigation.previousID == nil)
    }
    #expect(OutreachPreviewNavigation(ids: [], selectedID: nil).position == "0 emails")
  }

  @Test func awaitingResponseIncludesOnlySentUnansweredDeliveries() {
    #expect(CampaignDeliveryFilter.awaitingResponse.includes(send: .sent, response: .pending))
    #expect(CampaignDeliveryFilter.awaitingResponse.includes(send: .sent, response: .noResponse))
    for send in [SendState.notSent, .queued, .sending, .failed, .superseded] {
      #expect(!CampaignDeliveryFilter.awaitingResponse.includes(send: send, response: .pending))
      #expect(!CampaignDeliveryFilter.awaitingResponse.includes(send: send, response: .noResponse))
    }
    #expect(!CampaignDeliveryFilter.awaitingResponse.includes(send: .sent, response: .accepted))
    #expect(!CampaignDeliveryFilter.awaitingResponse.includes(send: .sent, response: .declined))
  }

  @Test func filteringKeepsAllOutcomesAccessibleWithoutReclassifyingThem() {
    for send in [SendState.notSent, .queued, .sending, .sent, .failed, .superseded] {
      for response in [ResponseState.pending, .accepted, .declined, .noResponse] {
        #expect(CampaignDeliveryFilter.all.includes(send: send, response: response))
        #expect(
          CampaignDeliveryFilter.accepted.includes(send: send, response: response)
            == (response == .accepted))
        #expect(
          CampaignDeliveryFilter.declined.includes(send: send, response: response)
            == (response == .declined))
        #expect(
          CampaignDeliveryFilter.failed.includes(send: send, response: response)
            == (send == .failed))
      }
    }
  }

  @Test func validationMovesToTheMatchingFieldWithoutLosingUnknownRules() {
    let messages =
      TemplateInputField.allCases.map(\.requiredMessage) + [
        "The server requires a different variable."
      ]
    let placement = TemplateValidationPlacement(messages: messages)
    for field in TemplateInputField.allCases { #expect(placement.requires(field)) }
    #expect(placement.requiresResponseLabels)
    #expect(placement.unplacedMessages == ["The server requires a different variable."])
    let valid = TemplateValidationPlacement(messages: [])
    #expect(!valid.requiresResponseLabels)
    #expect(valid.unplacedMessages.isEmpty)
  }
}
