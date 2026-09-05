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
      VStack(alignment: .leading, spacing: 20) {
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
          HStack(alignment: .top, spacing: 11) {
            Image(systemName: "quote.opening")
              .font(.system(size: 20, weight: .bold))
              .foregroundStyle(StudioPalette.blue.opacity(0.65))
            Text(primaryReason)
              .font(.body)
              .foregroundStyle(.primary)
              .lineLimit(3)
              .fixedSize(horizontal: false, vertical: true)
          }
          .frame(maxWidth: .infinity, alignment: .leading)
        }

        fitSignals

        if let firstRisk = presentation.brief.risks.first {
          HStack(alignment: .top, spacing: 8) {
            Image(systemName: "flag")
              .foregroundStyle(StudioPalette.coral)
            VStack(alignment: .leading, spacing: 3) {
              Text("Keep in mind").font(.caption.weight(.semibold))
              Text(firstRisk).font(.callout).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
              if presentation.brief.risks.count > 1 {
                Text("\(presentation.brief.risks.count - 1) more in match evidence")
                  .font(.caption).foregroundStyle(.secondary)
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

        if detailsExpanded {
          Divider()
          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
            if let performanceSummary = presentation.performanceSummary {
              Text(performanceSummary)
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            }
            if let recentMedianViews = presentation.recentMedianViews {
              statistic("Recent median views", value: recentMedianViews)
            }
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
        }
      }
      .padding(22)
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
      columns: [GridItem(.adaptive(minimum: 140), spacing: 8)], alignment: .leading, spacing: 8
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
    HStack(alignment: .top, spacing: 7) {
      Image(systemName: category.symbol)
        .foregroundStyle(category.color)
        .frame(width: 16)
      VStack(alignment: .leading, spacing: 3) {
        Text(label).font(.caption).foregroundStyle(.secondary)
        Text(value).font(.caption.weight(.semibold))
          .fixedSize(horizontal: false, vertical: true)
      }
      Spacer(minLength: 0)
    }
    .padding(10)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    .background(category.color.opacity(0.055), in: RoundedRectangle(cornerRadius: 10))
    .accessibilityElement(children: .combine)
  }

  private var detailsButton: some View {
    Button {
      withAnimation(WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)) {
        detailsExpanded.toggle()
      }
    } label: {
      Label(
        detailsExpanded ? "Close match evidence" : "Explore fit & evidence",
        systemImage: detailsExpanded ? "chevron.up" : "chevron.down")
    }
    .buttonStyle(.plain)
    .font(.callout)
    .foregroundStyle(StudioPalette.blue)
    .accessibilityValue(detailsExpanded ? "Expanded" : "Collapsed")
    .help("Read the full match reasoning, fit dimensions, risks, and evidence")
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
      Text("\(candidate.creator.contacts.count) contact options")
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

    if let responseState = candidate.outreach.responseState {
      Text("Response: \(responseState.displayName)")
        .font(.caption)
        .foregroundStyle(.secondary)
    }
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
