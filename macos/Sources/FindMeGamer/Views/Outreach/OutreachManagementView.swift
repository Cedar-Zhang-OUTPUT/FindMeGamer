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
      Picker("Outreach section", selection: $model.selectedTab) {
        ForEach(OutreachManagementTab.allCases, id: \.self) { tab in
          Text(tab.displayName).tag(tab)
        }
      }
      .pickerStyle(.segmented)
      .labelsHidden()
      .padding()

      Divider()

      selectedContent
    }
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
