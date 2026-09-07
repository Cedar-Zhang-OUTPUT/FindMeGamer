import FindMeGamerCore
import Foundation

struct OutreachPreviewNavigation: Equatable {
  let ids: [UUID]
  let selectedID: UUID?

  var index: Int? { selectedID.flatMap { ids.firstIndex(of: $0) } }
  var position: String { index.map { "\($0 + 1) of \(ids.count)" } ?? "\(ids.count) emails" }
  var previousID: UUID? {
    guard let index, index > 0 else { return nil }
    return ids[index - 1]
  }
  var nextID: UUID? {
    guard let index, index + 1 < ids.count else { return nil }
    return ids[index + 1]
  }
}

enum CampaignDeliveryFilter: String, CaseIterable {
  case all = "All"
  case accepted = "Accepted"
  case declined = "Declined"
  case awaitingResponse = "Awaiting response"
  case failed = "Failed"

  func includes(send: SendState, response: ResponseState) -> Bool {
    switch self {
    case .all: true
    case .accepted: response == .accepted
    case .declined: response == .declined
    case .awaitingResponse: send == .sent && (response == .pending || response == .noResponse)
    case .failed: send == .failed
    }
  }
}

enum TemplateInputField: CaseIterable {
  case name, subject, message, acceptedLabel, declinedLabel

  var requiredMessage: String {
    switch self {
    case .name: "Template Name is required."
    case .subject: "Subject is required."
    case .message: "Markdown Body is required."
    case .acceptedLabel: "Accepted CTA Label is required."
    case .declinedLabel: "Declined CTA Label is required."
    }
  }
}

/// Only positions existing model validation. Unknown rules remain visible verbatim.
struct TemplateValidationPlacement: Equatable {
  let messages: [String]
  func requires(_ field: TemplateInputField) -> Bool { messages.contains(field.requiredMessage) }
  var requiresResponseLabels: Bool { requires(.acceptedLabel) || requires(.declinedLabel) }
  var unplacedMessages: [String] {
    messages.filter { message in
      !TemplateInputField.allCases.contains { $0.requiredMessage == message }
    }
  }
}
