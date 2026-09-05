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
          feedback(error, systemImage: "arrow.clockwise.circle", color: .orange)
        }

        if campaign.sendBatches.isEmpty {
          ContentUnavailableView(
            "No Send Batches", systemImage: "tray",
            description: Text("This Campaign has no send history yet."))
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
    WorkspaceSurface(style: .elevated) {
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

        CampaignMetricGrid(metrics: campaign.metrics)
      }
      .padding(WorkspaceDesign.spaceL)
    }
  }

  private func campaignTitle(
    _ campaign: OutreachCampaign,
    lineLimit: Int,
    fixedWidth: Bool
  ) -> some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXS) {
      Text("CAMPAIGN")
        .font(.caption2.weight(.bold))
        .tracking(1.4)
        .foregroundStyle(Color.accentColor)

      Text(campaign.game.name)
        .font(.system(.largeTitle, design: .serif, weight: .semibold))
        .tracking(-0.4)
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
    GroupBox {
      VStack(spacing: 0) {
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
    } label: {
      HStack {
        Text(batch.templateName ?? "Send Batch")
          .font(.headline)
        Text("Version \(batch.templateVersion ?? 0)")
          .foregroundStyle(.secondary)
        Spacer()
        Text(batch.state.displayName)
        Text(batch.requestedAt, style: .date)
          .foregroundStyle(.secondary)
      }
    }
  }
}

private struct DeliveryRow: View {
  let delivery: Delivery
  let writesEnabled: Bool
  let canResend: Bool
  let resend: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(alignment: .firstTextBaseline) {
        VStack(alignment: .leading, spacing: 2) {
          Text(delivery.creator?.name ?? "Creator")
            .font(.headline)
          Text(delivery.recipientEmail)
            .font(.caption)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
        }
        Spacer()
        Text(delivery.sendState.displayName)
        Text(delivery.responseState.displayName)
          .foregroundStyle(.secondary)
        if delivery.canResend == true {
          Button("Resend", action: resend)
            .disabled(!writesEnabled || !canResend)
            .help(writesEnabled ? "Resend this email" : "Unavailable while offline")
        }
      }

      if let subject = delivery.renderedSubject {
        Text(subject)
          .font(.callout.weight(.medium))
      }
      if let markdown = delivery.renderedMarkdown {
        Text(markdown)
          .font(.callout)
          .foregroundStyle(.secondary)
          .lineLimit(4)
      }
      if let failure = delivery.smtpFailure {
        Label(failure.message, systemImage: "exclamationmark.triangle")
          .font(.callout)
          .foregroundStyle(.red)
          .textSelection(.enabled)
      }
      HStack(spacing: 12) {
        if let sentAt = delivery.sentAt {
          Text("Sent \(sentAt, style: .relative)")
        } else if let failedAt = delivery.failedAt {
          Text("Failed \(failedAt, style: .relative)")
        } else if let createdAt = delivery.createdAt {
          Text("Created \(createdAt, style: .relative)")
        }
        if let respondedAt = delivery.respondedAt {
          Text("Responded \(respondedAt, style: .relative)")
        }
      }
      .font(.caption)
      .foregroundStyle(.secondary)
    }
    .padding(.vertical, 10)
  }
}
