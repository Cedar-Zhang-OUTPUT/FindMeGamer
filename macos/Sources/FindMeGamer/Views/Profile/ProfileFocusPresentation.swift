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

/// Reorders existing fields for reading, without summarizing, scoring, or hiding risk text.
struct ProfileOverviewGrouping {
  let positioning: [ProfileDisplayField]
  let focus: [ProfileDisplayField]
  let risks: [ProfileDisplayField]
  let context: [ProfileDisplayField]

  init(primary: [ProfileDisplayField]) {
    let riskLabels: Set<String> = ["Brand Safety", "Collaboration Risks", "Promotion Risks"]
    let focusLabels: Set<String> = ["Promotion Fit", "Core Gameplay Loop"]
    positioning = primary.filter { $0.label == "Positioning" }
    focus = primary.filter { focusLabels.contains($0.label) }
    risks = primary.filter { riskLabels.contains($0.label) }
    context = primary.filter {
      $0.label != "Positioning" && !focusLabels.contains($0.label) && !riskLabels.contains($0.label)
    }
  }
}

struct ProfileOverview: View {
  let fields: [ProfileDisplayField]
  let type: ProfileType

  var body: some View {
    let presentation = ProfileOverviewPresentation(fields: fields, type: type)
    let groups = ProfileOverviewGrouping(primary: presentation.primary)
    VStack(alignment: .leading, spacing: 18) {
      ForEach(Array(groups.positioning.enumerated()), id: \.offset) { _, positioning in
        VStack(alignment: .leading, spacing: 6) {
          ForEach(Array(positioning.values.enumerated()), id: \.offset) { _, value in
            Text(value)
              .font(.system(size: 20, weight: .medium, design: .rounded))
              .tracking(-0.3)
              .lineSpacing(2)
              .fixedSize(horizontal: false, vertical: true)
          }
          if let annotation = positioning.annotation {
            Text(annotation).font(.caption2).foregroundStyle(.secondary)
          }
        }
        .textSelection(.enabled)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Positioning")
      }

      ForEach(Array(groups.focus.enumerated()), id: \.offset) { _, field in
        ProfileInsightCard(field: field)
      }

      if !groups.risks.isEmpty {
        VStack(alignment: .leading, spacing: 12) {
          ForEach(Array(groups.risks.enumerated()), id: \.offset) { _, field in
            ProfileInsightCard(field: field)
          }
        }
        .padding(13)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(StudioPalette.amber.opacity(0.055), in: RoundedRectangle(cornerRadius: 13))
        .accessibilityIdentifier("profile.overview.risks")
      }

      if !groups.context.isEmpty {
        Divider()
        LazyVGrid(
          columns: [GridItem(.adaptive(minimum: 250), spacing: 24, alignment: .leading)],
          alignment: .leading, spacing: 18
        ) {
          ForEach(Array(groups.context.enumerated()), id: \.offset) { _, field in
            ProfileInsightCard(field: field)
          }
        }
      } else if presentation.primary.isEmpty {
        Label(
          "Brief unavailable",
          systemImage: "text.magnifyingglass"
        )
        .foregroundStyle(.secondary)
        .padding(.vertical, 12)
      }

      if !presentation.additional.isEmpty {
        ProfileEvidenceSection(
          title: "More Details",
          symbol: "square.stack.3d.up", tone: .identity
        ) {
          FactSection(fields: presentation.additional)
        }
        .accessibilityIdentifier("profile.completeBrief")
      }
    }
  }
}
