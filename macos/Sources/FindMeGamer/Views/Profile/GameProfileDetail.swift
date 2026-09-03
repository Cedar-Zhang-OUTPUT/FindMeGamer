import FindMeGamerCore
import SwiftUI

struct GameProfileDetail: View {
  let presentation: GameProfilePresentation

  init(profile: FindMeGamerCore.GameProfile) {
    presentation = GameProfilePresentation(profile: profile)
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      ViewThatFits(in: .horizontal) {
        HStack(alignment: .top, spacing: 14) {
          sourceColumn
          analysisColumn
        }
        .frame(minWidth: 610)

        VStack(alignment: .leading, spacing: 14) {
          sourceColumn
          analysisColumn
        }
      }

      DisclosureGroup("Game Brief") {
        FactSection(title: "AI Analysis", fields: presentation.briefFields)
          .padding(.top, 8)
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
