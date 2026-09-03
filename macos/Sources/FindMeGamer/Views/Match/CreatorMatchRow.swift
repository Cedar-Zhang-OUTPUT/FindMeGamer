import FindMeGamerCore
import SwiftUI

enum MatchOutreachActionPolicy {
  static func isEligibleForNewSend(_ candidate: MatchCandidate) -> Bool {
    guard candidate.creator.contactAvailable,
      let email = candidate.creator.contact?.email,
      !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else {
      return false
    }
    guard candidate.outreach.responseState != .accepted,
      candidate.outreach.responseState != .declined
    else {
      return false
    }
    return candidate.outreach.sendState == nil || candidate.outreach.sendState == .notSent
  }

  static func canSendNew(_ candidate: MatchCandidate, writesEnabled: Bool) -> Bool {
    writesEnabled && isEligibleForNewSend(candidate)
  }

  static func resendDeliveryID(_ candidate: MatchCandidate) -> UUID? {
    guard let deliveryID = candidate.outreach.deliveryID,
      candidate.outreach.sendState == .sent || candidate.outreach.sendState == .failed,
      candidate.outreach.responseState != .accepted,
      candidate.outreach.responseState != .declined
    else {
      return nil
    }
    return deliveryID
  }

  static func canResend(_ candidate: MatchCandidate, writesEnabled: Bool) -> Bool {
    writesEnabled && resendDeliveryID(candidate) != nil
  }

  static func newSendUnavailableReason(_ candidate: MatchCandidate) -> String? {
    if candidate.outreach.responseState == .accepted { return "Response accepted" }
    if candidate.outreach.responseState == .declined { return "Response declined" }
    guard candidate.creator.contactAvailable,
      let email = candidate.creator.contact?.email,
      !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else {
      return "Email unavailable"
    }
    if let sendState = candidate.outreach.sendState, sendState != .notSent {
      return "Outreach: \(sendState.displayName)"
    }
    return nil
  }
}

struct MatchCandidatePresentation: Equatable, Identifiable {
  let source: MatchCandidate
  let id: UUID
  let name: String
  let avatarURL: URL?
  let label: String
  let reasons: [String]
  let performanceSummary: String?
  let subscriberCount: Int?
  let recentAverageViews: Int?
  let recentMedianViews: Int?
  let brief: MatchBriefPresentation

  init(candidate: MatchCandidate) {
    source = candidate
    id = candidate.creator.id
    name = candidate.creator.name
    avatarURL = ArtworkURLPolicy.validated(candidate.creator.avatarURL.flatMap(URL.init(string:)))
    label = candidate.label.displayName
    reasons = candidate.reasons
    performanceSummary = candidate.creator.performanceSummary
    subscriberCount = candidate.creator.subscriberCount
    recentAverageViews = candidate.creator.recentAverageViews
    recentMedianViews = candidate.creator.recentMedianViews
    brief = MatchBriefPresentation(brief: candidate.brief)
  }
}

struct CreatorMatchRow: View {
  let presentation: MatchCandidatePresentation
  @Binding var isSelected: Bool
  let writesEnabled: Bool
  let onOpenProfile: () -> Void
  let onSend: () -> Void
  let onResend: (UUID) -> Void

  @State private var detailsExpanded = false

  private var candidate: MatchCandidate { presentation.source }
  private var isNewSendEligible: Bool {
    MatchOutreachActionPolicy.isEligibleForNewSend(candidate)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .top, spacing: 12) {
        if isNewSendEligible {
          Toggle("Select \(presentation.name)", isOn: $isSelected)
            .labelsHidden()
            .toggleStyle(.checkbox)
            .disabled(!writesEnabled)
            .accessibilityIdentifier(MatchAccessibility.creatorSelect(presentation.id))
            .help("Select this Creator for Outreach")
        }

        AsyncArtwork(url: presentation.avatarURL, fallbackSystemImage: "person.crop.circle")
          .frame(width: 64, height: 64)
          .clipShape(Circle())

        VStack(alignment: .leading, spacing: 5) {
          Button(presentation.name, action: onOpenProfile)
            .buttonStyle(.link)
            .font(.headline)
            .help("Open this Creator Profile")

          Text(presentation.label)
            .font(.subheadline.weight(.medium))

          if let performanceSummary = presentation.performanceSummary {
            Text(performanceSummary)
              .font(.callout)
              .foregroundStyle(.secondary)
          }

          statistics
        }

        Spacer(minLength: 12)
        outreachActions
      }

      if !presentation.reasons.isEmpty {
        VStack(alignment: .leading, spacing: 4) {
          Text("Match Reasons")
            .font(.subheadline.weight(.semibold))
          ForEach(presentation.reasons, id: \.self) { reason in
            Text("• \(reason)")
          }
        }
      }

      DisclosureGroup(MatchCopy.viewDetails, isExpanded: $detailsExpanded) {
        MatchBriefView(presentation: presentation.brief)
          .padding(.top, 8)
      }
    }
    .padding(14)
    .background(Color.secondary.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
    .accessibilityIdentifier(MatchAccessibility.creator(presentation.id))
  }

  @ViewBuilder private var statistics: some View {
    HStack(spacing: 12) {
      if let subscriberCount = presentation.subscriberCount {
        Text("\(subscriberCount.formatted()) subscribers")
      }
      if let recentAverageViews = presentation.recentAverageViews {
        Text("\(recentAverageViews.formatted()) recent average views")
      }
      if let recentMedianViews = presentation.recentMedianViews {
        Text("\(recentMedianViews.formatted()) recent median views")
      }
    }
    .font(.caption)
    .foregroundStyle(.secondary)
  }

  @ViewBuilder private var outreachActions: some View {
    VStack(alignment: .trailing, spacing: 7) {
      if let contact = candidate.creator.contact,
        !contact.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      {
        Text(contact.email)
          .font(.caption)
          .foregroundStyle(.secondary)
          .textSelection(.enabled)
      }

      if isNewSendEligible {
        Button(MatchCopy.sendEmail, action: onSend)
          .disabled(!MatchOutreachActionPolicy.canSendNew(candidate, writesEnabled: writesEnabled))
          .accessibilityIdentifier(MatchAccessibility.creatorSend(presentation.id))
          .help("Compose new Outreach for this Creator")
      } else if let reason = MatchOutreachActionPolicy.newSendUnavailableReason(candidate) {
        Text(reason)
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      if let deliveryID = MatchOutreachActionPolicy.resendDeliveryID(candidate) {
        Button(MatchCopy.resend) { onResend(deliveryID) }
          .disabled(!MatchOutreachActionPolicy.canResend(candidate, writesEnabled: writesEnabled))
          .accessibilityIdentifier(MatchAccessibility.creatorResend(presentation.id))
          .help("Explicitly resend this existing delivery")
      }

      if let responseState = candidate.outreach.responseState {
        Text("Response: \(responseState.displayName)")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
    }
    .controlSize(.small)
  }
}
