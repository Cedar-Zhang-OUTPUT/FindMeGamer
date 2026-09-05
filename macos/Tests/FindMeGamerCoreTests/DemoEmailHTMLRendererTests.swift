import Foundation
import Testing

@testable import FindMeGamerCore

@Suite struct DemoEmailHTMLRendererTests {
  @Test func preservesEmailParagraphsAndInlineMarkdownStyles() {
    let html = DemoEmailHTMLRenderer.render(
      "Hi creator,\n\nA **bold** and *friendly* note with `code`.\n— Sender")

    #expect(html.contains("Hi creator,<br><br>"))
    #expect(html.contains("<strong>bold</strong>"))
    #expect(html.contains("<em>friendly</em>"))
    #expect(html.contains("<code>code</code>"))
    #expect(html.contains("<br>— Sender"))
    #expect(!html.contains("**bold**"))
  }

  @Test func rawHTMLIsDisplayedAsTextAndNeverExecuted() {
    let html = DemoEmailHTMLRenderer.render(
      "<script>alert('demo')</script>\n<img src=x onerror=alert(1)>\n**Safe**")

    #expect(!html.contains("<script"))
    #expect(!html.contains("<img"))
    #expect(html.contains("&lt;script&gt;"))
    #expect(html.contains("&lt;img"))
    #expect(html.contains("<strong>Safe</strong>"))
  }

  @Test func onlyWebLinksAreEmittedAndTheirAttributesAreEscaped() {
    let html = DemoEmailHTMLRenderer.render(
      "[Press kit](https://example.com/press?a=1&b=2)\n[Unsafe](javascript:alert%281%29)\n[File](file:///tmp/example)"
    )

    #expect(html.contains("href=\"https://example.com/press?a=1&amp;b=2\""))
    #expect(html.contains(">Press kit</a>"))
    #expect(!html.contains("href=\"javascript:"))
    #expect(!html.contains("href=\"file:"))
    #expect(html.contains("Unsafe"))
    #expect(html.contains("File"))
  }

  @Test func templateAndRecipientPreviewsUseTheSameSafeRenderer() async throws {
    let service = DemoAPIService()
    let template = try #require(try await service.listTemplates().first)
    let body = "Hello **{{creator_name}}**,\n\nA *new* collaboration."
    let templatePreview = try await service.previewTemplate(
      TemplateDraft(
        id: template.id, name: template.name, subjectTemplate: "Hello", bodyMarkdown: body,
        acceptedLabel: template.acceptedLabel, declinedLabel: template.declinedLabel))
    #expect(templatePreview.html == DemoEmailHTMLRenderer.render(templatePreview.markdown))
    #expect(templatePreview.html.contains("<strong>Tactical Cedar</strong>"))

    let match = try #require(try await service.listMatches(cursor: nil).items.first)
    let result = try await service.match(id: match.id)
    let creator = try #require(result.recommendedMatches.first { $0.creator.contacts.count == 1 })
    let previews = try await service.previewSendBatch(
      SendBatchDraft(
        matchTaskID: match.id, creatorIDs: [creator.id], templateID: template.id,
        bodyMarkdownOverride: body))
    let recipientPreview = try #require(previews.first)
    #expect(recipientPreview.html == DemoEmailHTMLRenderer.render(recipientPreview.markdown))
    #expect(recipientPreview.html.contains("<em>new</em>"))
  }
}
