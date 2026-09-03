import FindMeGamerCore
import SwiftUI

struct SidebarView: View {
  @Binding var selection: AppDestination?

  var body: some View {
    List(selection: $selection) {
      ForEach(AppDestination.allCases) { destination in
        Label(destination.title, systemImage: destination.systemImage)
          .tag(destination)
      }
    }
    .listStyle(.sidebar)
    .navigationTitle("Find Me Gamer")
    .navigationSplitViewColumnWidth(min: 180, ideal: 220, max: 280)
  }
}
