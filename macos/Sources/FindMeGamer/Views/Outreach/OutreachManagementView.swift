import FindMeGamerCore
import SwiftUI

struct OutreachManagementView<EmailSettings: View>: View {
  @Bindable var model: OutreachManagementModel
  private let emailSettings: EmailSettings
  private let onStartMatch: (() -> Void)?
  private let onOpenCampaign: (UUID) -> Void

  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var tabDirection = WorkspaceMotionDirection.stationary

  init(
    model: OutreachManagementModel,
    onStartMatch: (() -> Void)? = nil,
    onOpenCampaign: @escaping (UUID) -> Void = { _ in },
    @ViewBuilder emailSettings: () -> EmailSettings
  ) {
    self.model = model
    self.onStartMatch = onStartMatch
    self.onOpenCampaign = onOpenCampaign
    self.emailSettings = emailSettings()
  }

  var body: some View {
    VStack(spacing: 0) {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        WorkspacePageHeader(WorkspacePageCopy.outreach)

        HStack {
          Picker("Outreach section", selection: selectedTab) {
            ForEach(OutreachManagementTab.allCases, id: \.self) { tab in
              Text(tab.displayName).tag(tab)
            }
          }
          .pickerStyle(.segmented)
          .labelsHidden()
          .frame(maxWidth: 420)

          Spacer(minLength: 0)
        }
      }
      .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
      .padding(.top, WorkspaceDesign.pageVerticalPadding)
      .padding(.bottom, WorkspaceDesign.spaceM)

      ZStack {
        selectedContent
          .id(model.selectedTab)
          .transition(
            WorkspaceMotionPolicy.transition(
              direction: tabDirection,
              role: .switcher,
              reduceMotion: reduceMotion))
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
      .clipped()
    }
    .workspaceCanvas()
    .navigationTitle("Outreach")
  }

  @ViewBuilder private var selectedContent: some View {
    switch model.selectedTab {
    case .campaigns:
      CampaignsView(model: model, onStartMatch: onStartMatch, onOpenCampaign: onOpenCampaign)
    case .templates:
      TemplatesView(model: model)
    case .emailSettings:
      emailSettings
    }
  }

  private var selectedTab: Binding<OutreachManagementTab> {
    Binding(
      get: { model.selectedTab },
      set: { tab in
        guard tab != model.selectedTab else { return }
        tabDirection = WorkspaceMotionPolicy.direction(
          from: model.selectedTab,
          to: tab,
          ordered: OutreachManagementTab.allCases)
        withAnimation(
          WorkspaceMotionPolicy.animation(for: .switcher, reduceMotion: reduceMotion)
        ) {
          model.selectedTab = tab
        }
      })
  }
}
