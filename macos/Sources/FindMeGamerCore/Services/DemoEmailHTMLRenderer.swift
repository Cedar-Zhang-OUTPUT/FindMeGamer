import Foundation

/// A small, inert renderer for local Demo emails. Production HTML remains server-owned.
enum DemoEmailHTMLRenderer {
  static func render(_ markdown: String) -> String {
    // Treat raw HTML as literal text before parsing inline Markdown. No author-provided tag
    // or attribute is copied to the output document.
    let literalHTML =
      markdown
      .replacingOccurrences(of: "<", with: "&lt;")
      .replacingOccurrences(of: ">", with: "&gt;")
    let attributed =
      (try? AttributedString(
        markdown: literalHTML,
        options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
      ?? AttributedString(markdown)

    let fragments = attributed.runs.map { run in
      var fragment = escape(String(attributed[run.range].characters))
        .replacingOccurrences(of: "\r\n", with: "\n")
        .replacingOccurrences(of: "\r", with: "\n")
        .replacingOccurrences(of: "\n", with: "<br>")
      if let intent = run.inlinePresentationIntent {
        if intent.contains(.code) { fragment = "<code>\(fragment)</code>" }
        if intent.contains(.stronglyEmphasized) { fragment = "<strong>\(fragment)</strong>" }
        if intent.contains(.emphasized) { fragment = "<em>\(fragment)</em>" }
      }
      if let link = run.link, let scheme = link.scheme?.lowercased(),
        ["http", "https"].contains(scheme), link.host?.isEmpty == false
      {
        fragment = "<a href=\"\(escape(link.absoluteString))\">\(fragment)</a>"
      }
      return fragment
    }
    return "<p>\(fragments.joined())</p>"
  }

  private static func escape(_ value: String) -> String {
    value
      .replacingOccurrences(of: "&", with: "&amp;")
      .replacingOccurrences(of: "<", with: "&lt;")
      .replacingOccurrences(of: ">", with: "&gt;")
      .replacingOccurrences(of: "\"", with: "&quot;")
      .replacingOccurrences(of: "'", with: "&#39;")
  }
}
