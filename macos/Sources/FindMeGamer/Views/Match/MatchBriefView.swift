import FindMeGamerCore
import SwiftUI

struct MatchBriefDimensionPresentation: Equatable, Identifiable {
  var id: String { title }
  let title: String
  let analysis: String
  let evidence: [String]
}

struct MatchBriefPresentation: Equatable {
  let dimensions: [MatchBriefDimensionPresentation]
  let strengths: [String]
  let risks: [String]
  let evidence: [String]
  let matchReasons: [String]

  init(brief: MatchBrief) {
    dimensions = [
      .init(
        title: "Content Fit", analysis: brief.contentFit.analysis,
        evidence: brief.contentFit.evidence),
      .init(
        title: "Audience Fit", analysis: brief.audienceFit.analysis,
        evidence: brief.audienceFit.evidence),
      .init(
        title: "Performance Fit", analysis: brief.performanceFit.analysis,
        evidence: brief.performanceFit.evidence),
      .init(
        title: "Promotion Fit", analysis: brief.promotionFit.analysis,
        evidence: brief.promotionFit.evidence),
      .init(
        title: "Brand Safety", analysis: brief.brandSafety.analysis,
        evidence: brief.brandSafety.evidence),
    ]
    strengths = brief.strengths
    risks = brief.risks
    evidence = brief.evidence
    matchReasons = brief.matchReasons
  }
}

enum MatchEvidenceSection: String, CaseIterable, Identifiable {
  case summary, content, audience, performance, promotion, safety

  var id: String { rawValue }

  init(category: MatchEvidenceCategory) {
    switch category {
    case .content: self = .content
    case .audience: self = .audience
    case .performance: self = .performance
    case .promotion: self = .promotion
    case .safety: self = .safety
    }
  }

  var category: MatchEvidenceCategory? {
    switch self {
    case .summary: nil
    case .content: .content
    case .audience: .audience
    case .performance: .performance
    case .promotion: .promotion
    case .safety: .safety
    }
  }

  var title: String {
    switch self {
    case .summary: "Summary"
    case .content: "Content"
    case .audience: "Audience"
    case .performance: "Performance"
    case .promotion: "Promotion"
    case .safety: "Brand safety"
    }
  }
}

enum MatchEvidenceDisplayPolicy {
  /// The first reason remains fully visible above the detail panel.
  static func additionalReasons(_ reasons: [String]) -> [String] { Array(reasons.dropFirst()) }
}

struct MatchRiskDisclosurePresentation: Equatable {
  let primaryRisk: String?
  let additionalRisks: [String]

  init(risks: [String]) {
    primaryRisk = risks.first
    additionalRisks = Array(risks.dropFirst())
  }

  var disclosureLabel: String {
    "\(additionalRisks.count) more \(additionalRisks.count == 1 ? "risk" : "risks")"
  }
}

struct MatchBriefView: View {
  let presentation: MatchBriefPresentation
  @Binding var selectedSection: MatchEvidenceSection
  var additionalReasons: [String] = []
  var performanceSummary: String?
  var recentMedianViews: Int?

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      ViewThatFits(in: .horizontal) {
        sectionPicker.pickerStyle(.segmented).labelsHidden().fixedSize()
        sectionPicker.pickerStyle(.menu)
      }

      if let category = selectedSection.category,
        let dimension = presentation.dimensions.first(where: { $0.title == category.title })
      {
        VStack(alignment: .leading, spacing: 14) {
          Text(dimension.analysis)
            .font(.callout)
            .fixedSize(horizontal: false, vertical: true)
          if selectedSection == .performance {
            if let performanceSummary {
              Text(performanceSummary).font(.callout).foregroundStyle(.secondary)
            }
            if let recentMedianViews {
              LabeledContent("Recent median views", value: recentMedianViews.formatted())
                .font(.callout)
            }
          }
          MatchTextList(title: "Evidence", values: dimension.evidence, color: category.color)
        }
      } else {
        summary
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .textSelection(.enabled)
  }

  private var sectionPicker: some View {
    Picker("Evidence", selection: $selectedSection) {
      ForEach(MatchEvidenceSection.allCases) { section in
        Text(section.title).tag(section)
      }
    }
  }

  private var summary: some View {
    VStack(alignment: .leading, spacing: 18) {
      MatchTextList(title: "More reasons", values: additionalReasons)
      MatchTextList(title: "Strengths", values: presentation.strengths, color: StudioPalette.mint)
      // Risks stay beside the candidate's visible risk, with their own disclosure.
      MatchTextList(title: "Supporting evidence", values: presentation.evidence)
      MatchTextList(title: "Additional match reasons", values: presentation.matchReasons)
    }
  }
}

private struct MatchTextList: View {
  let title: String
  let values: [String]
  var color: Color = .secondary

  var body: some View {
    if !values.isEmpty {
      VStack(alignment: .leading, spacing: 8) {
        Text(title)
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(color)
        ForEach(values, id: \.self) { value in
          HStack(alignment: .firstTextBaseline, spacing: 7) {
            Circle().fill(color).frame(width: 4, height: 4)
              .alignmentGuide(.firstTextBaseline) { $0[.bottom] - 2 }
            Text(value).font(.callout)
              .fixedSize(horizontal: false, vertical: true)
          }
        }
      }
    }
  }
}
