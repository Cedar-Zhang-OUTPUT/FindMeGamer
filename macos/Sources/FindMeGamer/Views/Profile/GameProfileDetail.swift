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
        ProfileEvidenceSection(
          title: "Steam",
          symbol: "gamecontroller", tone: .identity
        ) {
          sourceColumn
        }
        analysisColumn
      }
    }
  }

  private var sourceColumn: some View {
    FactSection(fields: presentation.sourceFacts)
      .frame(maxWidth: .infinity, alignment: .topLeading)
  }

  private var analysisColumn: some View {
    VStack(alignment: .leading, spacing: 14) {
      Label("AI Analysis", systemImage: "sparkles")
        .font(.caption.weight(.medium))
        .foregroundStyle(.secondary)
        .accessibilityAddTraits(.isHeader)
      ForEach(
        GameProfileSection.allCases.filter { $0 != .gameBrief }, id: \.self
      ) { section in
        ProfileEvidenceSection(
          title: section.title,
          symbol: evidenceSymbol(section), tone: evidenceTone(section)
        ) {
          FactSection(contextTitle: section.title, fields: presentation.sections[section] ?? [])
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
