import FindMeGamerCore
import SwiftUI

struct CampaignsView: View {
  @Bindable var model: OutreachManagementModel

  var body: some View {
    Group {
      if model.isLoadingCampaigns && model.campaigns.isEmpty {
        ProgressView("Loading Campaigns…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if model.campaigns.isEmpty {
        ContentUnavailableView {
          Label("No Campaigns", systemImage: "paperplane")
        } description: {
          Text(model.campaignsError ?? "Sent outreach will appear here.")
        } actions: {
          if model.campaignsError != nil {
            Button("Try Again") {
              Task { await model.loadCampaigns() }
            }
          }
        }
      } else {
        List(model.campaigns) { campaign in
          NavigationLink(value: OutreachManagementRoute.campaign(campaign.id)) {
            CampaignRow(campaign: campaign)
          }
        }
        .listStyle(.inset)
        .safeAreaInset(edge: .top, spacing: 0) {
          if let error = model.campaignsError {
            CampaignErrorBanner(message: error) {
              Task { await model.loadCampaigns() }
            }
          }
        }
      }
    }
    .task {
      if model.campaigns.isEmpty {
        await model.loadCampaigns()
      }
    }
  }
}

private struct CampaignRow: View {
  let campaign: CampaignSummary

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(alignment: .firstTextBaseline) {
        Text(campaign.game.name)
          .font(.headline)
        Spacer()
        Text(campaign.state.displayName)
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      HStack(spacing: 18) {
        CampaignMetric(label: "Sent Creators", value: "\(campaign.metrics.sentCreators)")
        CampaignMetric(label: "Accepted", value: "\(campaign.metrics.accepted)")
        CampaignMetric(label: "Declined", value: "\(campaign.metrics.declined)")
        CampaignMetric(label: "No Response", value: "\(campaign.metrics.noResponse)")
        CampaignMetric(label: "Failed", value: "\(campaign.metrics.failed)")
        CampaignMetric(
          label: "Response Rate",
          value: campaign.metrics.responseRate.formatted(.percent.precision(.fractionLength(0))))
      }

      Text("Latest activity \(campaign.latestActivityAt, style: .relative)")
        .font(.caption)
        .foregroundStyle(.secondary)
    }
    .padding(.vertical, 6)
  }
}

struct CampaignMetric: View {
  let label: String
  let value: String

  var body: some View {
    VStack(alignment: .leading, spacing: 2) {
      Text(value)
        .font(.headline.monospacedDigit())
      Text(label)
        .font(.caption)
        .foregroundStyle(.secondary)
    }
    .accessibilityElement(children: .combine)
  }
}

private struct CampaignErrorBanner: View {
  let message: String
  let retry: () -> Void

  var body: some View {
    HStack {
      Label(message, systemImage: "exclamationmark.triangle")
        .foregroundStyle(.red)
        .textSelection(.enabled)
      Spacer()
      Button("Try Again", action: retry)
    }
    .padding(10)
    .background(.bar)
  }
}
