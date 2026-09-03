import Foundation
import Testing

@testable import FindMeGamer
@testable import FindMeGamerCore

@Suite struct LibraryStructureTests {
  @Test func libraryContractUsesExactCopyAccessibilityAndDesktopDimensions() {
    #expect(LibraryLayout.headerRowCount == 2)
    #expect(LibraryLayout.searchMaximumWidth == 360)
    #expect(LibraryLayout.gridMinimumWidth == 240)
    #expect(LibraryLayout.gridMaximumWidth == 340)
    #expect(LibraryLayout.profileTypes == [.game, .creator])
    #expect(LibraryCopy.searchPlaceholder == "Search Profiles…")
    #expect(LibraryCopy.onlyCollection == "Only Collection")
    #expect(LibraryCopy.analyzeRequest == "Analyze Request")
    #expect(LibraryCopy.empty == "No profiles found.")
    #expect(LibraryAccessibility.profileType == "library.profile-type")
    #expect(LibraryAccessibility.onlyCollection == "library.only-collection")
    #expect(LibraryAccessibility.search == "library.search")
    #expect(LibraryAccessibility.analyzeRequest == "library.analyze-request")
    #expect(LibraryAccessibility.grid == "library.grid")
  }

  @Test func activeAnalysisBadgeHidesNonpositiveCountsAndShowsPositiveCount() {
    #expect(LibraryBadge.visibleCount(for: -1) == nil)
    #expect(LibraryBadge.visibleCount(for: 0) == nil)
    #expect(LibraryBadge.visibleCount(for: 3) == 3)
  }

  @Test func cardPresentationsExtractOnlyApprovedPublicSummaryFields() {
    let gameID = UUID(uuidString: "10000000-0000-4000-8000-000000000001")!
    let game = FindMeGamerCore.GameProfileCard(
      id: gameID,
      name: "Signal Garden",
      steamAppID: "730",
      canonicalURL: "https://store.steampowered.com/app/730",
      favorite: true,
      currentFacts: [
        "short_description": .string("Build a cooperative signal network."),
        "genres": .array([.string("Strategy"), .string("Co-op"), .string("Puzzle")]),
        "cover_image_url": .string("https://cdn.example.test/game.jpg"),
        "hidden_rank": .integer(1),
      ],
      brief: [:],
      sourceStatus: [:],
      lastAnalyzedAt: nil,
      nextAnalysisAt: nil)

    let creatorID = UUID(uuidString: "20000000-0000-4000-8000-000000000001")!
    let creator = FindMeGamerCore.CreatorProfileCard(
      id: creatorID,
      name: "Tactical Cedar",
      youtubeChannelID: "UC-cedar",
      canonicalURL: "https://youtube.com/@tacticalcedar",
      favorite: false,
      currentFacts: [
        "avatar_url": .string("http://images.example.test/avatar.png"),
        "subscriber_count": .integer(125_000),
        "score": .number(0.99),
      ],
      brief: [
        "performance_context": .object(["value": .string("Consistent recent views")]),
        "content_focus": .object([
          "values": .array([.string("Strategy"), .string("Indie"), .string("Reviews")])
        ]),
      ],
      sourceStatus: [:],
      lastAnalyzedAt: nil,
      nextAnalysisAt: nil,
      contact: CreatorContact(
        email: "creator@example.test", availability: .discovered, source: "channel_about",
        sourceURL: nil, validationState: "valid"))

    let gamePresentation = GameCardPresentation(card: game)
    #expect(gamePresentation.name == "Signal Garden")
    #expect(gamePresentation.summary == "Build a cooperative signal network.")
    #expect(gamePresentation.tags == ["Strategy", "Co-op", "Puzzle"])
    #expect(gamePresentation.artworkURL?.absoluteString == "https://cdn.example.test/game.jpg")
    #expect(gamePresentation.isFavorite)

    let creatorPresentation = CreatorCardPresentation(card: creator)
    #expect(creatorPresentation.name == "Tactical Cedar")
    #expect(creatorPresentation.subscriberCount == 125_000)
    #expect(creatorPresentation.performanceSummary == "Consistent recent views")
    #expect(creatorPresentation.tags == ["Strategy", "Indie", "Reviews"])
    #expect(
      creatorPresentation.artworkURL?.absoluteString == "http://images.example.test/avatar.png")
    #expect(creatorPresentation.contactAvailability == "Discovered")
    #expect(!creatorPresentation.isFavorite)
  }

  @Test func wrongShapesAndInternalFieldsProduceUnavailablePresentation() {
    let game = FindMeGamerCore.GameProfileCard(
      id: UUID(), name: "Safe Game", steamAppID: "1", canonicalURL: "https://game.test",
      favorite: false,
      currentFacts: [
        "short_description": .boolean(true),
        "genres": .object(["rank": .string("First")]),
        "cover_image_url": .string("javascript:alert(1)"),
      ],
      brief: ["hidden_rank": .object(["value": .string("Do not show")])],
      sourceStatus: [:], lastAnalyzedAt: nil, nextAnalysisAt: nil)
    let creator = FindMeGamerCore.CreatorProfileCard(
      id: UUID(), name: "Safe Creator", youtubeChannelID: "UC-safe",
      canonicalURL: "https://youtube.com/@safe", favorite: false,
      currentFacts: [
        "subscriber_count": .string("secret count"),
        "avatar_url": .string("data:image/png;base64,AAAA"),
      ],
      brief: [
        "performance_context": .object(["reason": .string("Private")]),
        "content_focus": .object(["rank": .array([.string("Top")])]),
      ],
      sourceStatus: [:], lastAnalyzedAt: nil, nextAnalysisAt: nil, contact: nil)

    let gamePresentation = GameCardPresentation(card: game)
    #expect(gamePresentation.summary == nil)
    #expect(gamePresentation.tags.isEmpty)
    #expect(gamePresentation.artworkURL == nil)

    let creatorPresentation = CreatorCardPresentation(card: creator)
    #expect(creatorPresentation.subscriberCount == nil)
    #expect(creatorPresentation.performanceSummary == nil)
    #expect(creatorPresentation.tags.isEmpty)
    #expect(creatorPresentation.artworkURL == nil)
    #expect(creatorPresentation.contactAvailability == "Unavailable")
  }

  @Test func artworkPolicyAcceptsOnlyAbsoluteWebURLsAndUsesSystemCache() {
    #expect(ArtworkURLPolicy.validated(URL(string: "https://cdn.example.test/a.png")) != nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "http://images.example.test/a.png")) != nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "file:///tmp/a.png")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "data:image/png;base64,AAAA")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "javascript:alert(1)")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "/relative/a.png")) == nil)
    #expect(ArtworkURLPolicy.validated(URL(string: "https:///hostless.png")) == nil)

    let configuration = ArtworkLoader.makeConfiguration()
    #expect(configuration.urlCache === URLCache.shared)
    #expect(configuration.requestCachePolicy == .useProtocolCachePolicy)
  }
}
