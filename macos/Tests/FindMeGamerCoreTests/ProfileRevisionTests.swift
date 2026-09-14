import Foundation
import Testing

@testable import FindMeGamerCore

@Suite struct ProfileRevisionTests {
  @Test func unknownSnapshotIsNotClaimedAsChanged() {
    let id = UUID()
    #expect(
      !ProfileRevisionComparison(
        profileType: .game, profileID: id, snapshotRevision: nil, currentRevision: 8
      ).hasChanged)
    #expect(
      !ProfileRevisionComparison(
        profileType: .game, profileID: id, snapshotRevision: 8, currentRevision: 8
      ).hasChanged)
    #expect(
      ProfileRevisionComparison(
        profileType: .creator, profileID: id, snapshotRevision: 2, currentRevision: 8
      ).hasChanged)
  }
}
