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
  }

  private var displayedCampaign: OutreachCampaign? {
    guard model.selectedCampaignID == campaignID, model.selectedCampaign?.id == campaignID else {
      return nil
    }
    return model.selectedCampaign
  }

  private func campaignContent(_ campaign: OutreachCampaign) -> some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 22) {
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
      .padding(24)
      .frame(maxWidth: 1_100, alignment: .leading)
      .frame(maxWidth: .infinity)
    }
  }

  private func campaignHeader(_ campaign: OutreachCampaign) -> some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .firstTextBaseline) {
        Text(campaign.game.name)
          .font(.largeTitle.bold())
        Text(campaign.state.displayName)
          .foregroundStyle(.secondary)
        Spacer()
      }
      HStack(spacing: 22) {
        CampaignMetric(label: "Sent Creators", value: "\(campaign.metrics.sentCreators)")
        CampaignMetric(label: "Accepted", value: "\(campaign.metrics.accepted)")
        CampaignMetric(label: "Declined", value: "\(campaign.metrics.declined)")
        CampaignMetric(label: "No Response", value: "\(campaign.metrics.noResponse)")
        CampaignMetric(label: "Failed", value: "\(campaign.metrics.failed)")
        CampaignMetric(
          label: "Response Rate",
          value: campaign.metrics.responseRate.formatted(.percent.precision(.fractionLength(0))))
      }
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
