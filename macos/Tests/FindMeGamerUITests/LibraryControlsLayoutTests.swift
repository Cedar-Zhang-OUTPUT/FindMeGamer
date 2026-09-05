import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct LibraryControlsLayoutTests {
  @Test func wideLayoutKeepsOneSearchFieldBetweenTheFilters() {
    let plan = LibraryControlsLayoutPlan(availableWidth: 800, pickerWidth: 150, favoritesWidth: 100)
    #expect(plan.arrangement == .row)
    #expect(plan.widths == [150, 360, 100])
    #expect(plan.horizontalOffsets == [0, 166, 700])
    #expect(plan.height(for: [24, 34, 26]) == 34)
  }

  @Test func narrowLayoutMovesSearchBelowBothFiltersWithoutChangingControlOrder() {
    let plan = LibraryControlsLayoutPlan(availableWidth: 360, pickerWidth: 150, favoritesWidth: 100)
    #expect(plan.arrangement == .twoRows)
    #expect(plan.widths == [150, 360, 100])
    #expect(plan.horizontalOffsets == [0, 0, 260])
    #expect(plan.verticalOffsets(for: [24, 34, 26]) == [1, 36, 0])
    #expect(plan.height(for: [24, 34, 26]) == 70)
  }

  @Test func veryNarrowLayoutStacksControlsInsteadOfOverflowingTheDetailColumn() {
    let plan = LibraryControlsLayoutPlan(availableWidth: 200, pickerWidth: 150, favoritesWidth: 100)
    #expect(plan.arrangement == .stacked)
    #expect(plan.widths == [200, 200, 200])
    #expect(plan.verticalOffsets(for: [24, 34, 26]) == [0, 34, 78])
    for index in plan.widths.indices {
      #expect(plan.horizontalOffsets[index] + plan.widths[index] <= plan.width)
    }
  }

  @Test func profileCountsUseSingularOnlyForOneProfile() {
    #expect(LibraryCopy.profileCount(1, type: .creator, hasMore: false) == "1 creator")
    #expect(LibraryCopy.profileCount(1, type: .game, hasMore: true) == "1 game loaded")
    #expect(LibraryCopy.profileCount(0, type: .creator, hasMore: false) == "0 creators")
    #expect(LibraryCopy.profileCount(2, type: .game, hasMore: false) == "2 games")
  }
}
