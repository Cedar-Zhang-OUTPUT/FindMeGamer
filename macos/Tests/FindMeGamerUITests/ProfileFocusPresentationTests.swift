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

  private func field(_ label: String) -> ProfileDisplayField {
    ProfileDisplayField(label: label, values: ["Sample"], annotation: nil)
  }
}
