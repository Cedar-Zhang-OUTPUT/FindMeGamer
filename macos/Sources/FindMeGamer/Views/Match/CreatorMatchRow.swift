import FindMeGamerCore
import SwiftUI

enum MatchOutreachActionPolicy {
  static func isEligibleForNewSend(_ candidate: MatchCandidate) -> Bool {
    guard candidate.creator.contactAvailable,
      candidate.creator.contacts.contains(where: {
        !$0.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      })
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
      candidate.creator.contacts.contains(where: {
        !$0.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      })
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
  @State private var isHovered = false

  private var candidate: MatchCandidate { presentation.source }
  private var previewPolicy: MatchCandidatePreviewPolicy {
    MatchCandidatePreviewPolicy(reasons: presentation.reasons)
  }
  private var isNewSendEligible: Bool {
    MatchOutreachActionPolicy.isEligibleForNewSend(candidate)
  }

  var body: some View {
    WorkspaceSurface(style: isHovered ? .elevated : .card) {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        HStack(alignment: .top, spacing: WorkspaceDesign.spaceM) {
          if isNewSendEligible {
            Toggle("Select \(presentation.name)", isOn: $isSelected)
              .labelsHidden()
              .toggleStyle(.checkbox)
              .disabled(!writesEnabled)
              .accessibilityIdentifier(MatchAccessibility.creatorSelect(presentation.id))
              .help("Select this Creator for Outreach")
          }

          AsyncArtwork(url: presentation.avatarURL, fallbackSystemImage: "person.crop.circle")
            .frame(width: 70, height: 70)
            .clipShape(Circle())
            .overlay { Circle().strokeBorder(Color.primary.opacity(0.1)) }

          VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: WorkspaceDesign.spaceS) {
              Button(presentation.name, action: onOpenProfile)
                .buttonStyle(.plain)
                .font(.title3.weight(.semibold))
                .help("Open this Creator Profile")

              WorkspaceStatusLozenge(
                title: presentation.label,
                systemImage: labelSystemImage,
                tone: labelTone)
            }

            if let performanceSummary = presentation.performanceSummary {
              Text(performanceSummary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .lineLimit(2)
            }

            if let primaryReason = previewPolicy.primaryReason {
              Label(primaryReason, systemImage: "sparkle")
                .font(.callout.weight(.medium))
                .foregroundStyle(.primary)
                .lineLimit(2)
            }
          }

          Spacer(minLength: WorkspaceDesign.spaceM)
          outreachActions
        }

        statistics

        DisclosureGroup(isExpanded: $detailsExpanded) {
          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
            if !presentation.reasons.isEmpty {
              VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXS) {
                Text("Match Reasons")
                  .font(.headline)
                ForEach(presentation.reasons, id: \.self) { reason in
                  Label(reason, systemImage: "circle.fill")
                    .labelStyle(MatchReasonLabelStyle())
                }
              }
            }

            MatchBriefView(presentation: presentation.brief)
          }
          .padding(.top, WorkspaceDesign.spaceS)
        } label: {
          HStack(spacing: WorkspaceDesign.spaceXS) {
            Text(MatchCopy.viewDetails)
            if previewPolicy.additionalReasonCount > 0 {
              Text("+\(previewPolicy.additionalReasonCount) signals")
                .foregroundStyle(.secondary)
            }
          }
          .font(.callout.weight(.medium))
        }
      }
      .padding(WorkspaceDesign.spaceM)
    }
    .overlay {
      RoundedRectangle(cornerRadius: WorkspaceDesign.cardCornerRadius, style: .continuous)
        .strokeBorder(isSelected ? Color.accentColor : .clear, lineWidth: isSelected ? 2 : 0)
        .allowsHitTesting(false)
    }
    .onHover { isHovered = $0 }
    .animation(.easeOut(duration: 0.18), value: isHovered)
    .animation(.easeInOut(duration: 0.18), value: isSelected)
    .accessibilityIdentifier(MatchAccessibility.creator(presentation.id))
  }

  @ViewBuilder private var statistics: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: WorkspaceDesign.spaceS) {
        statisticItems
      }
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXS) {
        statisticItems
      }
    }
  }

  @ViewBuilder private var statisticItems: some View {
    if let subscriberCount = presentation.subscriberCount {
      statistic("Subscribers", value: subscriberCount)
    }
    if let recentAverageViews = presentation.recentAverageViews {
      statistic("Recent average", value: recentAverageViews)
    }
    if let recentMedianViews = presentation.recentMedianViews {
      statistic("Recent median", value: recentMedianViews)
    }
  }

  private func statistic(_ label: String, value: Int) -> some View {
    HStack(spacing: 5) {
      Text(value, format: .number)
        .fontWeight(.semibold)
        .monospacedDigit()
      Text(label)
        .foregroundStyle(.secondary)
    }
    .font(.caption)
    .padding(.horizontal, 9)
    .padding(.vertical, 6)
    .background(Color.secondary.opacity(0.07), in: Capsule())
    .accessibilityElement(children: .combine)
  }

  @ViewBuilder private var outreachActions: some View {
    VStack(alignment: .trailing, spacing: 7) {
      if let contact = candidate.creator.contacts.first(where: {
        !$0.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
      }) {
        Text(contact.email)
          .font(.caption)
          .foregroundStyle(.secondary)
          .textSelection(.enabled)
        if candidate.creator.contacts.count > 1 {
          Text("+\(candidate.creator.contacts.count - 1) email options")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      if isNewSendEligible {
        Button(MatchCopy.sendEmail, action: onSend)
          .buttonStyle(.borderedProminent)
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

  private var labelTone: WorkspaceTone {
    if presentation.label.localizedCaseInsensitiveContains("strong") { return .success }
    if presentation.label.localizedCaseInsensitiveContains("good") { return .accent }
    return .neutral
  }

  private var labelSystemImage: String {
    if presentation.label.localizedCaseInsensitiveContains("strong") { return "sparkles" }
    if presentation.label.localizedCaseInsensitiveContains("good") {
      return "checkmark.circle.fill"
    }
    return "minus.circle.fill"
  }
}

private struct MatchReasonLabelStyle: LabelStyle {
  func makeBody(configuration: Configuration) -> some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
      configuration.icon
        .font(.system(size: 5))
        .foregroundStyle(Color.accentColor)
      configuration.title
    }
  }
}
