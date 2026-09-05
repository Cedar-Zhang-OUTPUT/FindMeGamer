import Foundation

/// Presentation state only. The model's matching server preview remains the send authority.
enum OutreachComposerStage: String, CaseIterable, Identifiable {
  case recipients = "Recipients"
  case message = "Message"
  case review = "Review & send"

  var id: Self { self }

  var previous: Self? {
    switch self {
    case .recipients: nil
    case .message: .recipients
    case .review: .message
    }
  }

  static func initial(unresolvedRecipients: Int) -> Self {
    unresolvedRecipients > 0 ? .recipients : .message
  }

  static func canReview(unresolvedRecipients: Int, subject: String, body: String) -> Bool {
    unresolvedRecipients == 0
      && !subject.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      && !body.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }
}
