import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct ProfileFocusPresentationTests {
  @Test func theOverviewKeepsDecisionRisksVisibleWithoutLosingAnyBriefFields() {
    let fields = [
      field("Positioning"), field("Genres"), field("Audience"),
      field("Promotion Fit"), field("Collaboration Risks"), field("Brand Safety"),
      field("A future brief field"),
    ]
    let overview = ProfileOverviewPresentation(fields: fields, type: .creator)

    #expect(
      overview.primary.map(\.label) == [
        "Positioning", "Audience", "Promotion Fit", "Collaboration Risks", "Brand Safety",
      ])
    #expect(overview.additional.map(\.label) == ["Genres", "A future brief field"])
    #expect(overview.primary.count + overview.additional.count == fields.count)
  }

  @Test func gameOverviewRetainsPromotionRisksAndDoesNotInventMissingFields() {
    let overview = ProfileOverviewPresentation(
      fields: [field("Visual Identity"), field("Promotion Risks"), field("Core Gameplay Loop")],
      type: .game)

    #expect(overview.primary.map(\.label) == ["Promotion Risks", "Core Gameplay Loop"])
    #expect(overview.additional.map(\.label) == ["Visual Identity"])
    #expect(ProfileOverviewPresentation(fields: [], type: .game).primary.isEmpty)
  }

  @Test func onlyCreatorProfilesExposeContactEditing() {
    #expect(ProfileDetailDestination.available(for: .game) == [.overview, .evidence])
    #expect(ProfileDetailDestination.available(for: .creator) == [.overview, .evidence, .contacts])
  }

  @Test func overviewGroupingPutsExactRiskTextBeforeSecondaryContextWithoutDroppingFields() {
    let risk = ProfileDisplayField(
      label: "Collaboration Risks", values: ["A qualified risk, not an app verdict.", "Timing matters."],
      annotation: "AI Inference · Confidence: Low")
    let fields = [
      field("Audience"), field("Positioning"), field("Promotion Fit"), risk,
      field("Brand Safety"), field("Content Focus"), field("Unknown Future Field"),
    ]
    let groups = ProfileOverviewGrouping(primary: fields)

    #expect(groups.positioning.map(\.label) == ["Positioning"])
    #expect(groups.focus.map(\.label) == ["Promotion Fit"])
    #expect(groups.risks == [risk, field("Brand Safety")])
    #expect(groups.context.map(\.label) == ["Audience", "Content Focus", "Unknown Future Field"])
    #expect(
      groups.positioning.count + groups.focus.count + groups.risks.count + groups.context.count
        == fields.count)
  }

  @Test func gameGroupingKeepsFullGameplayAndRiskFieldsWithoutInventingCollaborationScores() {
    let fields = [field("Positioning"), field("Core Gameplay Loop"), field("Promotion Risks")]
    let groups = ProfileOverviewGrouping(primary: fields)
    #expect(groups.focus == [field("Core Gameplay Loop")])
    #expect(groups.risks == [field("Promotion Risks")])
    #expect(groups.context.isEmpty)
    #expect(ProfileOverviewGrouping(primary: []).positioning.isEmpty)
  }

  private func field(_ label: String) -> ProfileDisplayField {
    ProfileDisplayField(label: label, values: ["Sample"], annotation: nil)
  }
}
