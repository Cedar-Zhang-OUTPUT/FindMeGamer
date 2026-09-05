import FindMeGamerCore
import SwiftUI

enum ProfileDetailDestination: String, CaseIterable, Hashable {
  case overview, evidence, contacts

  var title: String {
    switch self {
    case .overview: "Overview"
    case .evidence: "Sources & Analysis"
    case .contacts: "Contacts & Notes"
    }
  }

  static func available(for type: ProfileType) -> [Self] {
    type == .creator ? [.overview, .evidence, .contacts] : [.overview, .evidence]
  }
}

/// Presentation-only partition: all facts retain their server order and every
/// field has a destination. Risk information stays in the default decision view.
struct ProfileOverviewPresentation {
  let primary: [ProfileDisplayField]
  let additional: [ProfileDisplayField]

  init(fields: [ProfileDisplayField], type: ProfileType) {
    let primaryLabels: Set<String> =
      type == .game
      ? [
        "Positioning", "Core Gameplay Loop", "Target Audience", "Content Hooks", "Promotion Risks",
      ]
      : [
        "Positioning", "Content Focus", "Audience", "Promotion Fit", "Brand Safety",
        "Collaboration Risks",
      ]
    let decisionFields = fields.filter { primaryLabels.contains($0.label) }
    if decisionFields.isEmpty {
      primary = Array(fields.prefix(1))
      additional = Array(fields.dropFirst())
    } else {
      primary = decisionFields
      additional = fields.filter { !primaryLabels.contains($0.label) }
    }
  }
}

struct ProfileOverview: View {
  let fields: [ProfileDisplayField]
  let type: ProfileType

  var body: some View {
    let presentation = ProfileOverviewPresentation(fields: fields, type: type)
    let positioning = presentation.primary.first { $0.label == "Positioning" }
    let insights = presentation.primary.filter { $0.label != "Positioning" }
    VStack(alignment: .leading, spacing: 20) {
      if let positioning {
        VStack(alignment: .leading, spacing: 9) {
          Label(
            type == .game ? "THE GAME, IN A FEW WORDS" : "MEET THE CREATOR",
            systemImage: "text.quote"
          )
          .font(.system(size: 10, weight: .bold, design: .rounded))
          .tracking(1.2)
          .foregroundStyle(StudioPalette.coral)
          ForEach(Array(positioning.values.enumerated()), id: \.offset) { _, value in
            Text(value)
              .font(.system(size: 23, weight: .medium, design: .rounded))
              .tracking(-0.45)
              .lineSpacing(3)
              .fixedSize(horizontal: false, vertical: true)
          }
          if let annotation = positioning.annotation {
            Text(annotation).font(.caption2).foregroundStyle(.secondary)
          }
        }
        .padding(.vertical, 7)
        .textSelection(.enabled)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Positioning")
      }

      if !insights.isEmpty {
        LazyVGrid(
          columns: [GridItem(.adaptive(minimum: 245), spacing: 12, alignment: .leading)],
          alignment: .leading, spacing: 12
        ) {
          ForEach(Array(insights.enumerated()), id: \.offset) { _, field in
            ProfileInsightCard(field: field)
          }
        }
      } else if positioning == nil {
        Label(
          "The brief is not available yet. Explore the source facts in Sources & Analysis.",
          systemImage: "text.magnifyingglass"
        )
        .foregroundStyle(.secondary)
        .padding(.vertical, 12)
      }

      if !presentation.additional.isEmpty {
        ProfileEvidenceSection(
          title: "More from the brief",
          subtitle: type == .game
            ? "Themes, style, and more ways to tell the story"
            : "Formats, style, and the wider context",
          symbol: "square.stack.3d.up", tone: .identity
        ) {
          FactSection(title: "Complete Brief", fields: presentation.additional)
        }
        .accessibilityIdentifier("profile.completeBrief")
      }
    }
  }
}
