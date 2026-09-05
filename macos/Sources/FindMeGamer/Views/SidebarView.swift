import FindMeGamerCore
import SwiftUI

struct SidebarView: View {
  @Binding var selection: AppDestination?

  var body: some View {
    List(selection: $selection) {
      Section("Workspace") {
        ForEach(AppDestination.allCases.filter { $0 != .settings }) { destination in
          destinationLabel(destination)
        }
      }
      Section {
        destinationLabel(.settings)
      }
    }
    .listStyle(.sidebar)
    .safeAreaInset(edge: .top, spacing: 0) {
      VStack(spacing: 0) {
        HStack(spacing: WorkspaceDesign.spaceS) {
          SignalMark()
            .frame(width: 44, height: 44)
            .background(
              LinearGradient(
                colors: [StudioPalette.blue.opacity(0.14), StudioPalette.mint.opacity(0.06)],
                startPoint: .topLeading, endPoint: .bottomTrailing),
              in: RoundedRectangle(cornerRadius: 14))

          Text("Find Me Gamer")
            .font(.system(size: 15, weight: .bold, design: .rounded))
            .foregroundStyle(StudioPalette.ink)

          Spacer(minLength: 0)
        }
        .padding(.horizontal, WorkspaceDesign.spaceM)
        .padding(.vertical, WorkspaceDesign.spaceM)
        .accessibilityElement(children: .combine)

        Rectangle().fill(StudioPalette.line.opacity(0.55)).frame(height: 0.5)
      }
      .background(.bar)
    }
    .navigationTitle("Find Me Gamer")
    .navigationSplitViewColumnWidth(min: 190, ideal: 216, max: 260)
  }

  private func destinationLabel(_ destination: AppDestination) -> some View {
    Label {
      Text(destination == .outreach ? "Outreach" : destination.title)
    } icon: {
      SidebarDestinationIcon(
        glyph: SidebarGlyph(destination: destination), isSelected: selection == destination)
    }
    .tag(destination)
    .padding(.vertical, 3)
  }
}
