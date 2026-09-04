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
          .buttonStyle(.plain)
          .listRowInsets(
            EdgeInsets(
              top: WorkspaceDesign.spaceXS,
              leading: WorkspaceDesign.pageHorizontalPadding,
              bottom: WorkspaceDesign.spaceXS,
              trailing: WorkspaceDesign.pageHorizontalPadding)
          )
          .listRowSeparator(.hidden)
          .listRowBackground(Color.clear)
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
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
    WorkspaceSurface(style: .card) {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        HStack(alignment: .top, spacing: WorkspaceDesign.spaceM) {
          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXS) {
            Text(campaign.game.name)
              .font(.title3.weight(.semibold))
              .foregroundStyle(.primary)
              .lineLimit(2)

            Text("Latest activity \(campaign.latestActivityAt, style: .relative)")
              .font(.caption)
              .foregroundStyle(.secondary)
          }

          Spacer(minLength: WorkspaceDesign.spaceM)

          WorkspaceStatusLozenge(
            title: campaign.state.displayName,
            systemImage: statusImage,
            tone: statusTone)

          Image(systemName: "chevron.forward")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.tertiary)
            .accessibilityHidden(true)
        }

        CampaignMetricGrid(metrics: campaign.metrics, compact: true)
      }
      .padding(WorkspaceDesign.spaceM)
    }
    .contentShape(RoundedRectangle(cornerRadius: WorkspaceDesign.cardCornerRadius))
  }

  private var statusTone: WorkspaceTone {
    switch campaign.state {
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

  private var statusImage: String {
    switch campaign.state {
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
}

private struct CampaignErrorBanner: View {
  let message: String
  let retry: () -> Void

  var body: some View {
    WorkspaceSurface(style: .quiet) {
      HStack(spacing: WorkspaceDesign.spaceM) {
        Label(message, systemImage: "exclamationmark.triangle")
          .foregroundStyle(.red)
          .textSelection(.enabled)
        Spacer()
        Button("Try Again", action: retry)
      }
      .padding(WorkspaceDesign.spaceS)
    }
    .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
    .padding(.top, WorkspaceDesign.spaceXS)
  }
}
