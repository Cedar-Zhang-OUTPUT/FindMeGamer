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
    VStack(alignment: .leading, spacing: 20) {
      VStack(alignment: .leading, spacing: 4) {
        Text("Behind the fit")
          .font(.system(.title3, design: .rounded, weight: .semibold))
        Text("Five perspectives. Explore the reasoning that matters to you.")
          .font(.callout).foregroundStyle(.secondary)
      }
      VStack(alignment: .leading, spacing: 10) {
        ForEach(presentation.dimensions) { dimension in
          MatchEvidenceDimensionView(dimension: dimension)
        }
      }

      LazyVGrid(
        columns: [GridItem(.adaptive(minimum: 240), spacing: 14, alignment: .top)],
        alignment: .leading, spacing: 14
      ) {
        if !presentation.strengths.isEmpty {
          MatchTextList(
            title: "What works", values: presentation.strengths, color: StudioPalette.mint
          )
          .padding(16)
          .frame(maxWidth: .infinity, alignment: .topLeading)
          .background(StudioPalette.mint.opacity(0.055), in: RoundedRectangle(cornerRadius: 12))
        }
        if !presentation.risks.isEmpty {
          MatchTextList(
            title: "Keep in mind", values: presentation.risks, color: StudioPalette.coral
          )
          .padding(16)
          .frame(maxWidth: .infinity, alignment: .topLeading)
          .background(StudioPalette.coral.opacity(0.055), in: RoundedRectangle(cornerRadius: 12))
        }
      }
      MatchTextList(title: "Supporting evidence", values: presentation.evidence)
      MatchTextList(title: "Additional match reasons", values: presentation.matchReasons)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .textSelection(.enabled)
  }
}

private struct MatchEvidenceDimensionView: View {
  let dimension: MatchBriefDimensionPresentation
  @State private var expanded = false

  private var category: MatchEvidenceCategory {
    MatchEvidenceCategory.allCases.first { $0.title == dimension.title } ?? .content
  }

  var body: some View {
    DisclosureGroup(isExpanded: $expanded) {
      VStack(alignment: .leading, spacing: 12) {
        Text(dimension.analysis)
          .font(.callout)
          .fixedSize(horizontal: false, vertical: true)
        MatchTextList(title: "Evidence", values: dimension.evidence, color: category.color)
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .padding(.top, 10)
      .padding(.leading, 43)
    } label: {
      HStack(alignment: .top, spacing: 11) {
        Image(systemName: category.symbol)
          .font(.system(size: 14, weight: .medium))
          .foregroundStyle(category.color)
          .frame(width: 32, height: 32)
          .background(category.color.opacity(0.09), in: RoundedRectangle(cornerRadius: 9))
        VStack(alignment: .leading, spacing: 5) {
          Text(dimension.title).font(.subheadline.weight(.semibold))
          if !expanded {
            Text(dimension.analysis)
              .font(.callout)
              .foregroundStyle(.secondary)
              .lineLimit(2)
              .fixedSize(horizontal: false, vertical: true)
          }
        }
        Spacer(minLength: 0)
      }
    }
    .padding(12)
    .background(Color.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 12))
    .tint(category.color)
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
