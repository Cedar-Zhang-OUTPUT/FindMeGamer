import FindMeGamerCore
import SwiftUI

enum OutreachManagementRoute: Hashable {
  case campaign(UUID)
}

struct OutreachManagementView<EmailSettings: View>: View {
  @Bindable var model: OutreachManagementModel
  private let emailSettings: EmailSettings

  init(
    model: OutreachManagementModel,
    @ViewBuilder emailSettings: () -> EmailSettings
  ) {
    self.model = model
    self.emailSettings = emailSettings()
  }

  var body: some View {
    VStack(spacing: 0) {
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        WorkspacePageHeader(WorkspacePageCopy.outreach)

        WorkspaceSurface(style: .quiet) {
          HStack {
            Picker("Outreach section", selection: $model.selectedTab) {
              ForEach(OutreachManagementTab.allCases, id: \.self) { tab in
                Text(tab.displayName).tag(tab)
              }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(maxWidth: 520)

            Spacer(minLength: 0)
          }
          .padding(WorkspaceDesign.spaceS)
        }
      }
      .padding(.horizontal, WorkspaceDesign.pageHorizontalPadding)
      .padding(.top, WorkspaceDesign.pageVerticalPadding)
      .padding(.bottom, WorkspaceDesign.spaceM)

      selectedContent
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
    .workspaceCanvas()
    .navigationTitle("Outreach")
    .navigationDestination(for: OutreachManagementRoute.self) { route in
      switch route {
      case .campaign(let id):
        CampaignDetailView(model: model, campaignID: id)
      }
    }
  }

  @ViewBuilder private var selectedContent: some View {
    switch model.selectedTab {
    case .campaigns:
      CampaignsView(model: model)
    case .templates:
      TemplatesView(model: model)
    case .emailSettings:
      emailSettings
    }
  }
}
