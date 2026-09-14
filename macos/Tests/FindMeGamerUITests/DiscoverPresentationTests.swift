import FindMeGamerCore
import Foundation
import Testing

@testable import FindMeGamer

@Suite struct DiscoverPresentationTests {
  @Test(arguments: [("Twitch", "https://www.twitch.tv/synthetic_fixture"),
                    ("Instagram", "https://www.instagram.com/synthetic_fixture")])
  func curatedProfileRetainsPlatformWhenStaleFactsAreHidden(platform: String, url: String) {
    let profile = CreatorProfile(
      id: UUID(), name: "Synthetic fixture", youtubeChannelID: nil,
      platformAccountID: "990000001", canonicalURL: url, favorite: false,
      currentFacts: ["followers_count": .number(42)], brief: [:],
      sourceStatus: ["freshness": .string("stale")], lastAnalyzedAt: nil,
      nextAnalysisAt: nil, contact: nil, manualNotes: nil,
      analysis: [:], modelMetadata: [:], promptMetadata: [:])
    let presentation = CreatorProfilePresentation(profile: profile)
    #expect(presentation.platformTitle == platform)
    #expect(presentation.sourceURL?.absoluteString == url)
    #expect(presentation.staleWarning?.contains(platform) == true)
    #expect(presentation.staleWarning?.contains("YouTube") == false)
  }

  @Test func xProfileUsesFollowerAndPostEvidenceWithRealIdentity() {
    let profile = CreatorProfile(
      id: UUID(), name: "Indie X", youtubeChannelID: nil,
      platformAccountID: "98765", canonicalURL: "https://x.com/indiex", favorite: false,
      currentFacts: ["follower_count": .number(1234), "post_count": .number(45)], brief: [:],
      sourceStatus: [:], lastAnalyzedAt: nil, nextAnalysisAt: nil, contact: nil, manualNotes: nil,
      analysis: [:], modelMetadata: [:], promptMetadata: [:])
    let presentation = CreatorProfilePresentation(profile: profile)
    #expect(presentation.platformTitle == "X")
    #expect(presentation.sourceFacts.contains { $0.label == "Followers" && $0.values == ["1234"] })
    #expect(presentation.sourceFacts.contains { $0.label == "Posts" && $0.values == ["45"] })
    #expect(
      !presentation.sourceFacts.contains { $0.label.contains("Video") || $0.label == "Subscribers" }
    )
    #expect(presentation.sourceFacts.first?.values == ["98765"])
  }
}
