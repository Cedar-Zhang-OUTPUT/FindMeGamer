import Foundation
import Testing

@testable import FindMeGamer

@Suite struct EmailMarkdownPresentationTests {
  @Test func previewPreservesParagraphsAndSignatureLineBreaks() {
    let rendered = EmailMarkdownPresentation.attributed(
      "Hi Tactical Cedar,\n\nWe think **Orbital Drift** fits your audience.\nWould you like a key?\n\n— The team"
    )

    #expect(
      String(rendered.characters)
        == "Hi Tactical Cedar,\n\nWe think Orbital Drift fits your audience.\nWould you like a key?\n\n— The team"
    )
    #expect(
      rendered.runs.contains { run in
        run.inlinePresentationIntent?.contains(.stronglyEmphasized) == true
          && String(rendered[run.range].characters) == "Orbital Drift"
      })
  }

  @Test func previewKeepsInlineEmphasisAndLinksWithoutDroppingSpacing() {
    let rendered = EmailMarkdownPresentation.attributed(
      "A *small* note.\n\n[Press kit](https://example.com/press)\nThanks!")

    #expect(String(rendered.characters) == "A small note.\n\nPress kit\nThanks!")
    #expect(
      rendered.runs.contains { run in
        run.inlinePresentationIntent?.contains(.emphasized) == true
      })
    #expect(
      rendered.runs.contains { run in
        run.link == URL(string: "https://example.com/press")
      })
  }
}
