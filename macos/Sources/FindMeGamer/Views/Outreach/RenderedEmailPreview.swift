import FindMeGamerCore
import SwiftUI

struct RenderedEmailPreview: View {
  let preview: RecipientPreview
  let acceptedLabel: String
  let declinedLabel: String

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        VStack(alignment: .leading, spacing: 4) {
          Text(preview.creatorName)
            .font(.title3.weight(.semibold))
          Text(preview.recipientEmail)
            .font(.callout)
            .foregroundStyle(.secondary)
            .textSelection(.enabled)
        }

        Divider()

        VStack(alignment: .leading, spacing: 6) {
          Text("Subject")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
          Text(preview.subject)
            .font(.headline)
            .textSelection(.enabled)
        }

        VStack(alignment: .leading, spacing: 8) {
          Text("Message")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
          renderedMarkdown
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
        }

        VStack(alignment: .leading, spacing: 10) {
          Label("System-managed response buttons", systemImage: "lock.fill")
            .font(.headline)
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
        .background(Color.accentColor.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
      }
      .padding(18)
    }
  }

  @ViewBuilder private var renderedMarkdown: some View {
    if let attributed = try? AttributedString(markdown: preview.markdown) {
      Text(attributed)
    } else {
      Text(preview.markdown)
    }
  }
}
