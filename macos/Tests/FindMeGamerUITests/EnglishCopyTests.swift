import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite
struct EnglishCopyTests {
  @Test func realWorkspaceDestinationsRemainTheFourEnglishProducts() {
    #expect(
      AppDestination.allCases.map(\.title)
        == ["Library", "Match", "Outreach Management", "Settings"])
    #expect(
      AppDestination.allCases.map(\.rawValue) == ["library", "match", "outreach", "settings"])
  }

  @Test func productionCopySurfacesContainNoCJKProductText() {
    let productCopy =
      AppDestination.allCases.map(\.title)
      + [
        LibraryCopy.searchPlaceholder,
        LibraryCopy.onlyCollection,
        LibraryCopy.analyzeRequest,
        LibraryCopy.empty,
      ]
      + MatchCopy.productionLabels
      + OutreachManagementTab.allCases.map(\.displayName)
      + [
        ConnectionTestStatus.success.displayName,
        ConnectionTestStatus.failed.displayName,
        ConnectionTestStatus.notTested.displayName,
      ]

    #expect(!productCopy.isEmpty)
    #expect(productCopy.allSatisfy { !$0.isEmpty && !containsCJK($0) })
  }
}

private func containsCJK(_ text: String) -> Bool {
  text.unicodeScalars.contains { scalar in
    switch scalar.value {
    case 0x3040...0x30FF, 0x3400...0x4DBF, 0x4E00...0x9FFF, 0xAC00...0xD7AF:
      true
    default:
      false
    }
  }
}
