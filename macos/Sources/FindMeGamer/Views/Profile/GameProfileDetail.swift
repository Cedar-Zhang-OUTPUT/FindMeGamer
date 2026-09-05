import FindMeGamerCore
import SwiftUI

struct GameProfileDetail: View {
  let presentation: GameProfilePresentation
  let destination: ProfileDetailDestination

  init(profile: FindMeGamerCore.GameProfile, destination: ProfileDetailDestination = .overview) {
    presentation = GameProfilePresentation(profile: profile)
    self.destination = destination
  }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      switch destination {
      case .overview, .contacts:
        ProfileOverview(fields: presentation.briefFields, type: .game)
      case .evidence:
        WorkspaceSectionHeader(
          "Sources & Analysis",
          subtitle:
            "Source facts and AI interpretation remain separate so you can judge the evidence.")
        ProfileEvidenceSection(
          title: "Steam source facts", subtitle: "Store details · not inferred",
          symbol: "gamecontroller", tone: .identity
        ) {
          sourceColumn
        }
        analysisColumn
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
        ProfileEvidenceSection(
          title: section.title, subtitle: "AI interpretation of the available evidence",
          symbol: evidenceSymbol(section), tone: evidenceTone(section)
        ) {
          FactSection(
            title: "AI Analysis — \(section.title)",
            fields: presentation.sections[section] ?? []
          )
        }
      }
    }
    .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private func evidenceSymbol(_ section: GameProfileSection) -> String {
    switch section {
    case .overview, .gameBrief: "text.quote"
    case .gameplay: "gamecontroller"
    case .visualStyle: "paintpalette"
    case .audience: "person.2"
    case .contentHooks: "lightbulb"
    case .risks: "exclamationmark.bubble"
    }
  }

  private func evidenceTone(_ section: GameProfileSection) -> ProfileStoryTone {
    switch section {
    case .audience: .audience
    case .contentHooks: .opportunity
    case .risks: .caution
    default: .identity
    }
  }
}
