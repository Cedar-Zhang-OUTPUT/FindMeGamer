import FindMeGamerCore
import SwiftUI

struct GameProfileDetail: View {
  let presentation: GameProfilePresentation

  init(profile: FindMeGamerCore.GameProfile) {
    presentation = GameProfilePresentation(profile: profile)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      WorkspaceSectionHeader(
        "Game Brief",
        subtitle: "The positioning signal your team can scan before opening the evidence.")
      FactSection(title: "Overview", fields: presentation.briefFields)

      DisclosureGroup {
        ViewThatFits(in: .horizontal) {
          HStack(alignment: .top, spacing: WorkspaceDesign.spaceM) {
            sourceColumn
            analysisColumn
          }
          .frame(minWidth: 610)

          VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
            sourceColumn
            analysisColumn
          }
        }
        .padding(.top, WorkspaceDesign.spaceS)
      } label: {
        Label("Explore source facts and AI evidence", systemImage: "doc.text.magnifyingglass")
          .font(.headline)
      }
    }
  }

  private var sourceColumn: some View {
    FactSection(title: "Source Facts", fields: presentation.sourceFacts)
      .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private var analysisColumn: some View {
    VStack(alignment: .leading, spacing: 14) {
      ForEach(
        GameProfileSection.allCases.filter { $0 != .gameBrief }, id: \.self
      ) { section in
        FactSection(
          title: "AI Analysis — \(section.title)",
          fields: presentation.sections[section] ?? [])
      }
    }
    .frame(maxWidth: .infinity, alignment: .topLeading)
  }
}
