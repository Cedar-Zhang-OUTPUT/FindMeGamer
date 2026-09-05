import FindMeGamerCore
import SwiftUI

struct CampaignDetailView: View {
  @Bindable var model: OutreachManagementModel
  let campaignID: UUID

  @Environment(\.workspaceWritesEnabled) private var writesEnabled

  var body: some View {
    Group {
      if let campaign = displayedCampaign {
        campaignContent(campaign)
      } else if model.isLoadingCampaignDetail {
        ProgressView("Loading Campaign…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else {
        ContentUnavailableView {
          Label("Campaign unavailable", systemImage: "exclamationmark.triangle")
        } description: {
          Text(model.campaignError ?? "This Campaign could not be loaded.")
        } actions: {
          Button("Try Again") {
            Task { await model.openCampaign(id: campaignID) }
          }
        }
      }
    }
    .navigationTitle(displayedCampaign?.game.name ?? "Campaign")
    .task(id: campaignID) {
      await model.openCampaign(id: campaignID)
    }
    .toolbar {
      ToolbarItem {
        Button {
          Task { await model.refreshCampaignsAndSelectedDetail() }
        } label: {
          Label("Refresh Campaign", systemImage: "arrow.clockwise")
        }
        .disabled(model.isLoadingCampaigns || model.isLoadingCampaignDetail)
        .help("Refresh Campaign")
      }
    }
  }

  private var displayedCampaign: OutreachCampaign? {
    guard model.selectedCampaignID == campaignID, model.selectedCampaign?.id == campaignID else {
      return nil
    }
    return model.selectedCampaign
  }

  private func campaignContent(_ campaign: OutreachCampaign) -> some View {
    ScrollView {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
        campaignHeader(campaign)

        if let message = model.resendMessage {
          feedback(message, systemImage: "checkmark.circle", color: .green)
        }
        if let error = model.resendError {
          feedback(error, systemImage: "exclamationmark.triangle", color: .red)
        }
        if let error = model.campaignError {
          HStack {
            feedback(error, systemImage: "arrow.clockwise.circle", color: .orange)
            Button("Try Again") { Task { await model.refreshCampaignsAndSelectedDetail() } }
              .disabled(model.isLoadingCampaignDetail)
          }
        }

        if campaign.sendBatches.isEmpty {
          ContentUnavailableView(
            "No deliveries yet", systemImage: "tray")
        } else {
          ForEach(campaign.sendBatches) { batch in
            SendBatchSection(
              batch: batch,
              writesEnabled: writesEnabled,
              canResend: model.canAttemptResend,
              resend: { deliveryID in
                Task { await model.resendDelivery(id: deliveryID) }
              })
          }
        }
      }
      .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
      .padding(.vertical, WorkspaceDesign.pageVerticalPadding)
      .frame(maxWidth: 1_100, alignment: .leading)
      .frame(maxWidth: .infinity)
    }
    .workspaceCanvas()
  }

  private func campaignHeader(_ campaign: OutreachCampaign) -> some View {
    WorkspaceSurface(style: .card) {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceL) {
        ViewThatFits(in: .horizontal) {
          HStack(alignment: .firstTextBaseline, spacing: WorkspaceDesign.spaceM) {
            campaignTitle(campaign, lineLimit: 1, fixedWidth: true)
            Spacer(minLength: WorkspaceDesign.spaceL)
            campaignStatus(campaign)
          }

          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceS) {
            campaignTitle(campaign, lineLimit: 3, fixedWidth: false)
            campaignStatus(campaign)
          }
        }

        Rectangle()
          .fill(StudioPalette.blue.opacity(0.14))
          .frame(height: 1)
          .accessibilityHidden(true)
        OutreachMetricSummary(metrics: campaign.metrics)
      }
      .padding(WorkspaceDesign.spaceL)
      .background(
        LinearGradient(
          colors: [StudioPalette.blue.opacity(0.08), StudioPalette.mint.opacity(0.025), .clear],
          startPoint: .topLeading, endPoint: .bottomTrailing))
    }
  }

  private func campaignTitle(
    _ campaign: OutreachCampaign,
    lineLimit: Int,
    fixedWidth: Bool
  ) -> some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXS) {
      Text(campaign.game.name)
        .font(.system(size: 29, weight: .semibold, design: .rounded))
        .tracking(-0.7)
        .foregroundStyle(StudioPalette.ink)
        .lineLimit(lineLimit)
        .fixedSize(horizontal: fixedWidth, vertical: false)
    }
  }

  private func campaignStatus(_ campaign: OutreachCampaign) -> some View {
    WorkspaceStatusLozenge(
      title: campaign.state.displayName,
      systemImage: statusImage(campaign.state),
      tone: statusTone(campaign.state))
  }

  private func statusTone(_ state: CampaignState) -> WorkspaceTone {
    switch state {
    case .completed:
      .success
    case .failed:
      .danger
    case .queued, .sending:
      .accent
    case .notStarted:
      .neutral
    }
  }

  private func statusImage(_ state: CampaignState) -> String {
    switch state {
    case .completed:
      "checkmark.circle.fill"
    case .failed:
      "exclamationmark.triangle.fill"
    case .queued:
      "clock.fill"
    case .sending:
      "paperplane.fill"
    case .notStarted:
      "circle.dashed"
    }
  }

  private func feedback(_ message: String, systemImage: String, color: Color) -> some View {
    Label(message, systemImage: systemImage)
      .foregroundStyle(color)
      .textSelection(.enabled)
      .padding(10)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(color.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
  }
}

private struct SendBatchSection: View {
  let batch: SendBatch
  let writesEnabled: Bool
  let canResend: (UUID) -> Bool
  let resend: (UUID) -> Void

  var body: some View {
    WorkspaceSurface(style: .card) {
      VStack(alignment: .leading, spacing: 0) {
        HStack(alignment: .top, spacing: 12) {
          Image(systemName: "envelope.badge")
            .font(.system(size: 18, weight: .light))
            .foregroundStyle(StudioPalette.blue)
            .frame(width: 36, height: 36)
            .background(StudioPalette.blue.opacity(0.07), in: RoundedRectangle(cornerRadius: 10))
            .accessibilityHidden(true)
          VStack(alignment: .leading, spacing: 5) {
            Text(batch.templateName ?? "Send Batch")
              .font(.system(.headline, design: .rounded))
            HStack(spacing: 8) {
              Text(batch.requestedAt, style: .date)
            }
            .font(.caption)
            .foregroundStyle(.secondary)
          }
          Spacer(minLength: 0)
          Text(batch.state.displayName)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
        }
        .padding(.vertical, 16)
        Divider()
        if batch.deliveries.isEmpty {
          Text("No deliveries in this batch.")
            .foregroundStyle(.secondary)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 8)
        } else {
          ForEach(Array(batch.deliveries.enumerated()), id: \.element.id) { index, delivery in
            if index > 0 { Divider() }
            DeliveryRow(
              delivery: delivery,
              writesEnabled: writesEnabled,
              canResend: canResend(delivery.id),
              resend: { resend(delivery.id) })
          }
        }
      }
      .padding(.horizontal, 18)
      .padding(.bottom, 4)
    }
  }
}

private struct DeliveryRow: View {
  let delivery: Delivery
  let writesEnabled: Bool
  let canResend: Bool
  let resend: () -> Void
  @State private var isConfirmingResend = false

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      ViewThatFits(in: .horizontal) {
        HStack(alignment: .firstTextBaseline, spacing: 16) {
          recipientHeading
          Spacer()
          deliveryStatus
        }
        VStack(alignment: .leading, spacing: 10) {
          recipientHeading
          deliveryStatus
        }
      }

      if delivery.renderedSubject != nil || delivery.renderedMarkdown != nil {
        DisclosureGroup {
          VStack(alignment: .leading, spacing: 10) {
            if let subject = delivery.renderedSubject {
              Text(subject)
                .font(.callout.weight(.medium))
                .fixedSize(horizontal: false, vertical: true)
                .textSelection(.enabled)
            }
            if let markdown = delivery.renderedMarkdown {
              Text(EmailMarkdownPresentation.attributed(markdown))
                .font(.callout)
                .lineSpacing(4)
                .foregroundStyle(.secondary)
            }
          }
          .frame(maxWidth: .infinity, alignment: .leading)
          .textSelection(.enabled)
          .padding(.top, 8)
        } label: {
          Text(delivery.renderedSubject ?? "Sent message")
            .font(.callout.weight(.medium))
            .lineLimit(2)
        }
      }
      if let failure = delivery.smtpFailure {
        Label(failure.message, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(.red)
          .textSelection(.enabled)
      }
      DisclosureGroup {
        VStack(alignment: .leading, spacing: 5) {
          if let version = delivery.templateVersion {
            Text("Template version \(version)")
          }
          if let sentAt = delivery.sentAt { Text("Sent \(sentAt.formatted())") }
          if let failedAt = delivery.failedAt { Text("Failed \(failedAt.formatted())") }
          if let createdAt = delivery.createdAt { Text("Created \(createdAt.formatted())") }
          if let respondedAt = delivery.respondedAt { Text("Responded \(respondedAt.formatted())") }
        }
      } label: {
        if let respondedAt = delivery.respondedAt {
          Text("Responded \(respondedAt, style: .relative)")
        } else if let sentAt = delivery.sentAt {
          Text("Sent \(sentAt, style: .relative)")
        } else if let failedAt = delivery.failedAt {
          Text("Failed \(failedAt, style: .relative)")
        } else if let createdAt = delivery.createdAt {
          Text("Created \(createdAt, style: .relative)")
        } else {
          Text("Delivery details")
        }
      }
      .font(.caption)
      .foregroundStyle(.secondary)
    }
    .padding(.vertical, 16)
    .confirmationDialog(
      "Resend this email?", isPresented: $isConfirmingResend, titleVisibility: .visible
    ) {
      Button("Resend") {
        guard writesEnabled && canResend else { return }
        resend()
      }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text("A new delivery attempt will be queued for \(delivery.recipientEmail).")
    }
  }

  private var recipientHeading: some View {
    HStack(spacing: 11) {
      Text(StudioPalette.initials(for: delivery.creator?.name ?? "Creator"))
        .font(.system(size: 13, weight: .medium, design: .rounded))
        .foregroundStyle(StudioPalette.ink)
        .frame(width: 34, height: 34)
        .background(
          StudioPalette.identityColor(for: delivery.creatorID.uuidString).opacity(0.13),
          in: Circle()
        )
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 3) {
        Text(delivery.creator?.name ?? "Creator")
          .font(.system(.headline, design: .rounded))
        Text(delivery.recipientEmail)
          .font(.caption)
          .foregroundStyle(.secondary)
          .textSelection(.enabled)
      }
    }
  }

  private var deliveryStatus: some View {
    HStack(spacing: 12) {
      Text(delivery.sendState.displayName)
        .font(.caption.weight(.medium))
        .foregroundStyle(delivery.sendState == .failed ? StudioPalette.coral : Color.secondary)
      Text(delivery.responseState.displayName)
        .font(.caption.weight(.medium))
        .foregroundStyle(delivery.responseState == .accepted ? StudioPalette.mint : Color.secondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 4)
        .background(
          delivery.responseState == .accepted
            ? StudioPalette.mint.opacity(0.08) : Color.secondary.opacity(0.055),
          in: Capsule())
      if delivery.canResend == true {
        Button("Resend") { isConfirmingResend = true }
          .disabled(!writesEnabled || !canResend)
          .help(writesEnabled ? "Resend this email" : "Unavailable while offline")
      }
    }
  }
}
