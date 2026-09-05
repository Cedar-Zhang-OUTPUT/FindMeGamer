import FindMeGamerCore
import SwiftUI

enum EmailMarkdownPresentation {
  static func attributed(_ markdown: String) -> AttributedString {
    // SwiftUI Text does not lay out the paragraph intents emitted by the full parser.
    // Preserve the authored email spacing while retaining inline Markdown formatting.
    (try? AttributedString(
      markdown: markdown,
      options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)))
      ?? AttributedString(markdown)
  }
}

struct RenderedEmailPreview: View {
  let preview: RecipientPreview
  let acceptedLabel: String
  let declinedLabel: String

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 24) {
        HStack(spacing: 12) {
          Text(StudioPalette.initials(for: preview.creatorName))
            .font(.system(size: 16, weight: .semibold, design: .rounded))
            .foregroundStyle(StudioPalette.ink)
            .frame(width: 43, height: 43)
            .background(StudioPalette.blue.opacity(0.1), in: Circle())
            .accessibilityHidden(true)
          VStack(alignment: .leading, spacing: 4) {
            Text("To \(preview.creatorName)")
              .font(.system(.headline, design: .rounded))
            Text(preview.recipientEmail)
              .font(.callout)
              .foregroundStyle(.secondary)
              .textSelection(.enabled)
          }
        }

        Divider()

        VStack(alignment: .leading, spacing: 6) {
          Text("Subject")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
          Text(preview.subject)
            .font(.system(size: 22, weight: .medium, design: .rounded))
            .tracking(-0.4)
            .foregroundStyle(StudioPalette.ink)
            .textSelection(.enabled)
        }

        VStack(alignment: .leading, spacing: 8) {
          Text("Message")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
          renderedMarkdown
            .font(.system(size: 15))
            .lineSpacing(6)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
        }

        VStack(alignment: .leading, spacing: 10) {
          Label("System-managed response buttons", systemImage: "lock.fill")
            .font(.callout.weight(.medium))
          Text("These response actions are inserted and tracked by the system.")
            .font(.caption)
            .foregroundStyle(.secondary)
          HStack(spacing: 10) {
            Button(acceptedLabel) {}
              .disabled(true)
            Button(declinedLabel) {}
              .disabled(true)
          }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(StudioPalette.blue.opacity(0.04), in: RoundedRectangle(cornerRadius: 12))
      }
      .padding(26)
      .frame(maxWidth: 720, alignment: .leading)
      .modifier(OutreachWritingSurface())
      .padding(24)
      .frame(maxWidth: .infinity)
    }
    .background(StudioPalette.canvas)
  }

  private var renderedMarkdown: some View {
    Text(EmailMarkdownPresentation.attributed(preview.markdown))
  }
}
