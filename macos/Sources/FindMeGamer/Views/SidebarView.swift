import FindMeGamerCore
import SwiftUI

struct SidebarView: View {
  @Binding var selection: AppDestination?

  var body: some View {
    List(selection: $selection) {
      Section("Workspace") {
        ForEach(AppDestination.allCases) { destination in
          Label {
            Text(destination.title)
          } icon: {
            SidebarDestinationIcon(
              glyph: SidebarGlyph(destination: destination),
              isSelected: selection == destination)
          }
          .tag(destination)
        }
      }
    }
    .listStyle(.sidebar)
    .safeAreaInset(edge: .top, spacing: 0) {
      VStack(spacing: 0) {
        HStack(spacing: WorkspaceDesign.spaceS) {
          SignalMark()

          VStack(alignment: .leading, spacing: 2) {
            Text("Find Me Gamer")
              .font(.headline)
            Text("Creator intelligence")
              .font(.caption)
              .foregroundStyle(.secondary)
          }

          Spacer(minLength: 0)
        }
        .padding(.horizontal, WorkspaceDesign.spaceM)
        .padding(.vertical, WorkspaceDesign.spaceM)
        .accessibilityElement(children: .combine)

        Divider()
      }
      .background(.bar)
    }
    .navigationTitle("Find Me Gamer")
    .navigationSplitViewColumnWidth(min: 180, ideal: 220, max: 280)
  }
}
