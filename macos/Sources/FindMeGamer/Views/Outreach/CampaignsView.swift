import FindMeGamerCore
import SwiftUI

struct CampaignsView: View {
  @Bindable var model: OutreachManagementModel
  var onStartMatch: (() -> Void)? = nil
  var onOpenCampaign: (UUID) -> Void = { _ in }

  var body: some View {
    Group {
      if model.isLoadingCampaigns && model.campaigns.isEmpty {
        ProgressView("Loading Campaigns…")
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if model.campaigns.isEmpty {
        ContentUnavailableView {
          Label(
            model.campaignsError == nil ? "Start a conversation" : "Campaigns unavailable",
            systemImage: "paperplane")
        } description: {
          Text(
            model.campaignsError
              ?? "Find creators for a game, select the people you want to reach, then compose your outreach. Delivery and replies will appear here."
          )
        } actions: {
          if model.campaignsError == nil, let onStartMatch {
            Button("Find creators", action: onStartMatch)
              .buttonStyle(.borderedProminent)
          }
          Button(model.campaignsError == nil ? "Refresh" : "Try Again") {
            Task { await model.loadCampaigns() }
          }
        }
      } else {
        VStack(alignment: .leading, spacing: 12) {
          HStack(alignment: .firstTextBaseline) {
            Text("Track your conversations")
              .font(.system(.title3, design: .rounded, weight: .semibold))
            Spacer()
            Text(
              "\(model.campaigns.count) \(model.campaigns.count == 1 ? "campaign" : "campaigns")"
            )
            .font(.caption)
            .foregroundStyle(.secondary)
          }
          .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)

          List(model.campaigns) { campaign in
            Button {
              onOpenCampaign(campaign.id)
            } label: {
              CampaignRow(campaign: campaign)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open campaign for \(campaign.game.name)")
            .accessibilityIdentifier("outreach.campaign.\(campaign.id.uuidString)")
            .listRowInsets(
              EdgeInsets(
                top: 6,
                leading: WorkspaceDesign.pageHorizontalPadding,
                bottom: 10,
                trailing: WorkspaceDesign.pageHorizontalPadding)
            )
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)
          }
          .listStyle(.plain)
          .scrollContentBackground(.hidden)
        }
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
    .toolbar {
      ToolbarItem {
        Button {
          Task { await model.loadCampaigns() }
        } label: {
          Label("Refresh Campaigns", systemImage: "arrow.clockwise")
        }
        .disabled(model.isLoadingCampaigns)
        .help("Refresh Campaigns")
      }
    }
  }
}

private struct CampaignRow: View {
  let campaign: CampaignSummary
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var isHovered = false

  private var identityColor: Color { StudioPalette.identityColor(for: campaign.game.id.uuidString) }

  var body: some View {
    WorkspaceSurface(style: .card) {
      VStack(alignment: .leading, spacing: 22) {
        HStack(alignment: .top, spacing: 14) {
          Group {
            if let cover = campaign.game.coverURL.flatMap({ URL(string: $0) }),
              ArtworkURLPolicy.validated(cover) != nil
            {
              AsyncArtwork(url: cover, fallbackSystemImage: "gamecontroller")
            } else {
              ZStack {
                identityColor.opacity(0.15)
                Image(systemName: "paperplane")
                  .font(.system(size: 23, weight: .light))
                  .foregroundStyle(identityColor)
              }
            }
          }
          .frame(width: 55, height: 62)
          .clipShape(RoundedRectangle(cornerRadius: 12))
          .accessibilityHidden(true)

          VStack(alignment: .leading, spacing: 8) {
            Text(campaign.game.name)
              .font(.system(size: 20, weight: .semibold, design: .rounded))
              .tracking(-0.4)
              .foregroundStyle(StudioPalette.ink)
              .lineLimit(2)
            Text("Latest activity \(campaign.latestActivityAt, style: .relative)")
              .font(.caption)
              .foregroundStyle(.secondary)
            WorkspaceStatusLozenge(
              title: campaign.state.displayName,
              systemImage: statusImage,
              tone: statusTone)
          }

          Spacer(minLength: 4)

          Image(systemName: "arrow.up.right")
            .font(.callout.weight(.medium))
            .foregroundStyle(isHovered ? identityColor : Color.secondary)
            .frame(width: 30, height: 30)
            .background(identityColor.opacity(isHovered ? 0.13 : 0.055), in: Circle())
            .accessibilityHidden(true)
        }

        OutreachMetricSummary(metrics: campaign.metrics, showsAll: false)
      }
      .padding(20)
      .background(
        LinearGradient(
          colors: [identityColor.opacity(0.035), .clear],
          startPoint: .topLeading, endPoint: .bottomTrailing))
    }
    .contentShape(Rectangle())
    .onHover { isHovered = $0 }
    .offset(y: isHovered && !reduceMotion ? -2 : 0)
    .animation(
      WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
      value: isHovered)
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

struct OutreachMetricSummary: View {
  let metrics: CampaignMetrics
  var showsAll = true

  private var items: [CampaignMetricPresentation] {
    CampaignMetricPresentation.items(metrics).filter {
      showsAll || $0.isPrimary || ($0.label == "Failed" && metrics.failed > 0)
    }
  }

  var body: some View {
    LazyVGrid(
      columns: [GridItem(.adaptive(minimum: 102), spacing: 18)], alignment: .leading, spacing: 18
    ) {
      ForEach(items) { item in
        VStack(alignment: .leading, spacing: 5) {
          Text(item.value)
            .font(
              .system(size: showsAll ? 30 : 26, weight: .medium, design: .rounded).monospacedDigit()
            )
            .tracking(-0.8)
            .foregroundStyle(metricColor(item))
          Label(item.label, systemImage: item.systemImage)
            .font(.caption)
            .foregroundStyle(
              item.label == "Failed" && metrics.failed > 0 ? StudioPalette.coral : Color.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
      }
    }
  }

  private func metricColor(_ item: CampaignMetricPresentation) -> Color {
    if item.label == "Failed", metrics.failed > 0 { return StudioPalette.coral }
    if item.label == "Accepted", metrics.accepted > 0 { return StudioPalette.mint }
    return StudioPalette.ink
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
