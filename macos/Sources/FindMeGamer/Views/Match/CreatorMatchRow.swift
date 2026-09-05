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

  @State private var evidenceSection: MatchEvidenceSection?
  @State private var isHovered = false
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  private var candidate: MatchCandidate { presentation.source }
  private var previewPolicy: MatchCandidatePreviewPolicy {
    MatchCandidatePreviewPolicy(reasons: presentation.reasons)
  }
  private var isNewSendEligible: Bool {
    MatchOutreachActionPolicy.isEligibleForNewSend(candidate)
  }

  var body: some View {
    WorkspaceSurface(style: .card) {
      VStack(alignment: .leading, spacing: 14) {
        ViewThatFits(in: .horizontal) {
          HStack(alignment: .center, spacing: 24) {
            identity.frame(minWidth: 230, maxWidth: .infinity, alignment: .leading)
            statistics
          }
          VStack(alignment: .leading, spacing: 16) {
            identity
            statistics
          }
        }

        if let primaryReason = previewPolicy.primaryReason {
          Text(primaryReason)
            .font(.body)
            .foregroundStyle(.primary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
        }

        fitSignals

        if let firstRisk = presentation.brief.risks.first {
          HStack(alignment: .top, spacing: 8) {
            Image(systemName: "flag")
              .foregroundStyle(StudioPalette.coral)
            VStack(alignment: .leading, spacing: 3) {
              Text(firstRisk).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
              if presentation.brief.risks.count > 1 {
                Button("All risks · \(presentation.brief.risks.count)") {
                  showEvidence(.summary)
                }
                .buttonStyle(.borderless)
                .font(.caption)
                .foregroundStyle(StudioPalette.coral)
              }
            }
          }
        }

        ViewThatFits(in: .horizontal) {
          HStack(alignment: .center) {
            detailsButton
            Spacer(minLength: 12)
            outreachActions
          }
          VStack(alignment: .leading, spacing: 12) {
            detailsButton
            outreachActions
          }
        }

        if evidenceSection != nil {
          Divider()
          MatchBriefView(
            presentation: presentation.brief,
            selectedSection: Binding(
              get: { evidenceSection ?? .summary },
              set: { showEvidence($0) }),
            additionalReasons: MatchEvidenceDisplayPolicy.additionalReasons(presentation.reasons),
            performanceSummary: presentation.performanceSummary,
            recentMedianViews: presentation.recentMedianViews)
        }
      }
      .padding(18)
      .background(isSelected ? StudioPalette.blue.opacity(0.035) : .clear)
    }
    .overlay {
      RoundedRectangle(cornerRadius: WorkspaceDesign.cardCornerRadius, style: .continuous)
        .strokeBorder(
          isSelected
            ? StudioPalette.blue.opacity(0.65)
            : isHovered ? StudioPalette.blue.opacity(0.22) : .clear,
          lineWidth: isSelected ? 1.5 : 1
        )
        .allowsHitTesting(false)
    }
    .shadow(color: StudioPalette.blue.opacity(isHovered ? 0.055 : 0), radius: 14, y: 6)
    .onHover { isHovered = $0 }
    .animation(
      WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
      value: isSelected
    )
    .animation(
      WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
      value: isHovered
    )
    .accessibilityIdentifier(MatchAccessibility.creator(presentation.id))
  }

  private var identity: some View {
    HStack(alignment: .center, spacing: 14) {
      Button(action: onOpenProfile) {
        AsyncArtwork(url: presentation.avatarURL, fallbackSystemImage: "person.crop.circle")
          .frame(width: 60, height: 60)
          .clipShape(Circle())
          .padding(4)
          .background(StudioPalette.mint.opacity(0.12), in: Circle())
          .overlay { Circle().strokeBorder(StudioPalette.mint.opacity(0.3)) }
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Open \(presentation.name) profile")
      VStack(alignment: .leading, spacing: 7) {
        creatorName
        matchLabel
      }
      Spacer(minLength: 0)
      if isNewSendEligible {
        Toggle("Select \(presentation.name)", isOn: $isSelected)
          .labelsHidden()
          .toggleStyle(.checkbox)
          .disabled(!writesEnabled)
          .accessibilityIdentifier(MatchAccessibility.creatorSelect(presentation.id))
          .help("Select this Creator for Outreach")
      }
    }
  }

  private var creatorName: some View {
    Button(presentation.name, action: onOpenProfile)
      .buttonStyle(.plain)
      .font(.system(size: 20, weight: .semibold, design: .rounded))
      .tracking(-0.4)
      .help("Open this Creator Profile")
  }

  private var matchLabel: some View {
    Label(
      presentation.label,
      systemImage: candidate.label == .limited ? "circle.lefthalf.filled" : "sparkle"
    )
    .font(.caption.weight(.semibold))
    .foregroundStyle(candidate.label == .limited ? StudioPalette.amber : StudioPalette.mint)
    .padding(.horizontal, 9)
    .padding(.vertical, 4)
    .background(
      (candidate.label == .limited ? StudioPalette.amber : StudioPalette.mint).opacity(0.09),
      in: Capsule())
  }

  private var fitSignals: some View {
    LazyVGrid(
      columns: [GridItem(.adaptive(minimum: 170), spacing: 8)], alignment: .leading, spacing: 8
    ) {
      fitSignal("Content", value: candidate.dimensionOutcomes.contentFit, category: .content)
      fitSignal("Audience", value: candidate.dimensionOutcomes.audienceFit, category: .audience)
      fitSignal(
        "Performance", value: candidate.dimensionOutcomes.performanceFit, category: .performance)
    }
  }

  private func fitSignal(_ label: String, value: String, category: MatchEvidenceCategory)
    -> some View
  {
    Button {
      showEvidence(MatchEvidenceSection(category: category))
    } label: {
      HStack(alignment: .firstTextBaseline, spacing: 5) {
        Text(label).foregroundStyle(.secondary)
        Text(value).fontWeight(.semibold)
          .fixedSize(horizontal: false, vertical: true)
        Image(systemName: "chevron.right").font(.system(size: 8, weight: .semibold))
          .foregroundStyle(category.color)
      }
      .font(.caption)
      .padding(.horizontal, 9)
      .padding(.vertical, 7)
      .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
      .background(category.color.opacity(0.065), in: RoundedRectangle(cornerRadius: 8))
    }
    .buttonStyle(.plain)
    .help("\(label) evidence")
    .accessibilityElement(children: .combine)
  }

  private var detailsButton: some View {
    Button {
      withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
        evidenceSection = evidenceSection == nil ? .summary : nil
      }
    } label: {
      Label(
        evidenceSection != nil ? "Close evidence" : "Evidence",
        systemImage: evidenceSection != nil ? "chevron.up" : "chevron.down")
    }
    .buttonStyle(.plain)
    .font(.callout)
    .foregroundStyle(StudioPalette.blue)
    .accessibilityValue(evidenceSection != nil ? "Expanded" : "Collapsed")
    .help("Read the full match reasoning, fit dimensions, risks, and evidence")
  }

  private func showEvidence(_ section: MatchEvidenceSection) {
    withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
      evidenceSection = section
    }
  }

  @ViewBuilder private var statistics: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 24) {
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
  }

  private func statistic(_ label: String, value: Int) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(value, format: .number)
        .font(.system(size: 22, weight: .semibold, design: .rounded))
        .tracking(-0.5)
        .monospacedDigit()
      Text(label)
        .font(.caption)
        .foregroundStyle(.secondary)
    }
    .accessibilityElement(children: .combine)
  }

  @ViewBuilder private var outreachActions: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 10) {
        contactSummary
        outreachControls
      }
      VStack(alignment: .leading, spacing: 6) {
        contactSummary
        outreachControls
      }
    }
    .controlSize(.small)
  }

  @ViewBuilder private var contactSummary: some View {
    if candidate.creator.contacts.count > 1 {
      Text("\(candidate.creator.contacts.count) emails")
        .font(.caption)
        .foregroundStyle(.secondary)
    } else if let contact = candidate.creator.contacts.first(where: {
      !$0.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }) {
      Text(contact.email)
        .font(.caption)
        .foregroundStyle(.secondary)
        .textSelection(.enabled)
        .lineLimit(1)
    }
  }

  private var outreachControls: some View {
    ViewThatFits(in: .horizontal) {
      HStack(spacing: 10) { outreachControlItems }
      VStack(alignment: .leading, spacing: 6) { outreachControlItems }
    }
  }

  @ViewBuilder private var outreachControlItems: some View {
    if isNewSendEligible {
      Button("Compose email", action: onSend)
        .buttonStyle(.bordered)
        .disabled(!MatchOutreachActionPolicy.canSendNew(candidate, writesEnabled: writesEnabled))
        .accessibilityIdentifier(MatchAccessibility.creatorSend(presentation.id))
        .help("Compose new Outreach for this Creator")
    } else if let reason = MatchOutreachActionPolicy.newSendUnavailableReason(candidate) {
      Text(reason)
        .font(.caption)
        .foregroundStyle(.secondary)
      if reason == "Email unavailable" {
        Button("Add email", action: onOpenProfile)
          .buttonStyle(.borderless)
          .help("Open this Creator Profile to add a contact email")
      }
    }

    if let deliveryID = MatchOutreachActionPolicy.resendDeliveryID(candidate) {
      Button(MatchCopy.resend) { onResend(deliveryID) }
        .disabled(!MatchOutreachActionPolicy.canResend(candidate, writesEnabled: writesEnabled))
        .accessibilityIdentifier(MatchAccessibility.creatorResend(presentation.id))
        .help("Explicitly resend this existing delivery")
    }

    if let responseState = candidate.outreach.responseState,
      responseState != .accepted && responseState != .declined
    {
      Text("Response: \(responseState.displayName)")
        .font(.caption)
        .foregroundStyle(.secondary)
    }
  }
}
