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

struct MatchBriefView: View {
  let presentation: MatchBriefPresentation

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      ForEach(presentation.dimensions) { dimension in
        VStack(alignment: .leading, spacing: 5) {
          Text(dimension.title)
            .font(.headline)
          Text(dimension.analysis)
          MatchTextList(title: "Evidence", values: dimension.evidence)
        }
      }

      MatchTextList(title: "Strengths", values: presentation.strengths)
      MatchTextList(title: "Risks", values: presentation.risks)
      MatchTextList(title: "Evidence", values: presentation.evidence)
      MatchTextList(title: "Match Reasons", values: presentation.matchReasons)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .textSelection(.enabled)
  }
}

private struct MatchTextList: View {
  let title: String
  let values: [String]

  var body: some View {
    if !values.isEmpty {
      VStack(alignment: .leading, spacing: 4) {
        Text(title)
          .font(.subheadline.weight(.semibold))
        ForEach(values, id: \.self) { value in
          Label(value, systemImage: "circle.fill")
            .labelStyle(MatchBulletLabelStyle())
        }
      }
    }
  }
}

private struct MatchBulletLabelStyle: LabelStyle {
  func makeBody(configuration: Configuration) -> some View {
    HStack(alignment: .firstTextBaseline, spacing: 7) {
      configuration.icon
        .font(.system(size: 4))
        .foregroundStyle(.secondary)
      configuration.title
    }
  }
}
