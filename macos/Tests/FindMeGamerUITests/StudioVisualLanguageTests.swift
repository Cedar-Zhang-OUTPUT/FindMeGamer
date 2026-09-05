import AppKit
import Foundation
import Testing

@testable import FindMeGamer

@Suite struct StudioVisualLanguageTests {
  @Test func identityColorIsStableAndDoesNotDependOnHashRandomization() {
    #expect(
      StudioPalette.identityIndex(for: "Tactical Cedar")
        == StudioPalette.identityIndex(for: "Tactical Cedar"))
    for name in ["Tactical Cedar", "Indie Orbit", "创作者", "", "  "] {
      #expect((0..<4).contains(StudioPalette.identityIndex(for: name)))
    }
  }

  @Test func monogramsUseNamesWithoutFabricatingPortraits() {
    #expect(StudioPalette.initials(for: "Tactical Cedar") == "TC")
    #expect(StudioPalette.initials(for: "  Indie   Orbit  ") == "IO")
    #expect(StudioPalette.initials(for: "Cedar") == "C")
    #expect(StudioPalette.initials(for: " ") == "?")
  }

  @MainActor
  @Test func originalCoverIsAvailableWithoutANetworkRequest() throws {
    let url = try #require(StudioArtwork.coverURL)
    #expect(url.isFileURL)
    let image = try #require(NSImage(contentsOf: url))
    #expect(image.size.width > image.size.height)
    #expect(image.size.width >= 1_000)
  }
}
