import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct ProfileStoryPresentationTests {
  @Test func profileMetricsUseOnlyAvailableSourceFactsAndDoNotRoundCounts() {
    let fields = [
      field("Subscribers", "120345"),
      field("Average Views", "Not available"),
      field("Public Videos", "256"),
      field("Rank", "1"),
      field("Promotion Fit", "Great"),
    ]
    let metrics = ProfileMetricPresentation.sourceMetrics(fields: fields, type: .creator)

    #expect(metrics.map(\.label) == ["Subscribers", "Public Videos"])
    #expect(metrics.map(\.value) == [120345.formatted(.number), 256.formatted(.number)])
    #expect(ProfileMetricPresentation.sourceMetrics(fields: [], type: .creator).isEmpty)
  }

  @Test func gameMetricsKeepSourceReviewLanguageWithoutTurningItIntoAnAppVerdict() {
    let metrics = ProfileMetricPresentation.sourceMetrics(
      fields: [
        field("Release Date", "2026-08-31"),
        field("Review Summary", "Very Positive"),
        field("Recommendations", ""),
      ], type: .game)

    #expect(metrics.map(\.label) == ["Release Date", "Review Summary"])
    #expect(metrics.map(\.value) == ["2026-08-31", "Very Positive"])
  }

  @Test func semanticColorsDescribeContentTypeNotAnInventedQualityScore() {
    #expect(ProfileStoryTone.forField("Audience") == .audience)
    #expect(ProfileStoryTone.forField("Promotion Fit") == .opportunity)
    #expect(ProfileStoryTone.forField("Brand Safety") == .caution)
    #expect(ProfileStoryTone.forField("Collaboration Risks") == .caution)
    #expect(ProfileStoryTone.forField("Promotion Risks") == .caution)
    #expect(ProfileStoryTone.forField("Content Focus") == .identity)
  }

  @Test func topicChipsUseOnlyExplicitMultiValueContentFocusWithoutSplittingProse() {
    let topics = ProfileDisplayField(
      label: "Content Focus", values: ["Strategy", "Simulation"], annotation: "Confidence: High")
    let prose = field("Content Focus", "Strategy, simulation, and why people play them.")
    let risks = ProfileDisplayField(
      label: "Collaboration Risks", values: ["Timing", "Availability"], annotation: nil)

    #expect(ProfileStoryTone.usesTopicChips(for: topics))
    #expect(!ProfileStoryTone.usesTopicChips(for: prose))
    #expect(!ProfileStoryTone.usesTopicChips(for: risks))
  }

  private func field(_ label: String, _ value: String) -> ProfileDisplayField {
    ProfileDisplayField(label: label, values: [value], annotation: nil)
  }
}
