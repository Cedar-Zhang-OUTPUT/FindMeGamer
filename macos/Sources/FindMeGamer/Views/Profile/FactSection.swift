import SwiftUI

enum ProfileFactLayout {
  /// Only source-backed scalar fields become compact rows. Narrative claims,
  /// lists, and any future field keep their full reading layout.
  static func usesInlineValue(_ field: ProfileDisplayField) -> Bool {
    let labels: Set<String> = [
      "Steam App ID", "YouTube Channel ID", "Country", "Published Date", "Release Date",
      "Coming Soon", "Free to Play", "Required Age", "Review Summary", "Recommendations",
      "Subscribers", "Total Views", "Public Videos", "Recent Public Videos",
      "Videos With View Counts", "Average Views", "Median Views", "Newest Video", "Oldest Video",
      "Uploads per 30 Days", "Publishing Sample", "Publishing Span (Days)",
    ]
    return field.values.count == 1 && labels.contains(field.label)
  }

  static func showsFieldTitle(
    _ field: ProfileDisplayField, fieldCount: Int, contextTitle: String?
  ) -> Bool {
    fieldCount != 1 || field.label != contextTitle
  }
}

struct FactSection: View {
  var title: String? = nil
  var contextTitle: String? = nil
  let fields: [ProfileDisplayField]

  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      if let title {
        Text(title)
          .font(.title3.weight(.semibold))
          .accessibilityAddTraits(.isHeader)
      }

      if fields.isEmpty {
        Text("Not available")
          .foregroundStyle(.secondary)
      } else {
        ForEach(Array(fields.enumerated()), id: \.offset) { _, field in
          VStack(alignment: .leading, spacing: 7) {
            if ProfileFactLayout.usesInlineValue(field) {
              ViewThatFits(in: .horizontal) {
                HStack(alignment: .firstTextBaseline, spacing: 16) {
                  fieldTitle(field).fixedSize()
                  Spacer(minLength: 16)
                  Text(field.values[0]).fixedSize()
                }
                VStack(alignment: .leading, spacing: 7) {
                  fieldTitle(field)
                  Text(field.values[0])
                    .fixedSize(horizontal: false, vertical: true)
                }
              }
            } else {
              if ProfileFactLayout.showsFieldTitle(
                field, fieldCount: fields.count, contextTitle: contextTitle)
              {
                fieldTitle(field)
              }
              if field.values.count == 1 {
                Text(field.values[0])
                  .lineSpacing(3)
                  .fixedSize(horizontal: false, vertical: true)
              } else {
                ForEach(Array(field.values.enumerated()), id: \.offset) { _, value in
                  Label(value, systemImage: "circle.fill")
                    .labelStyle(ProfileBulletLabelStyle())
                    .fixedSize(horizontal: false, vertical: true)
                }
              }
            }
            if let annotation = field.annotation {
              Text(annotation)
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.leading, 9)
                .overlay(alignment: .leading) {
                  RoundedRectangle(cornerRadius: 1)
                    .fill(StudioPalette.blue.opacity(0.3))
                    .frame(width: 2)
                }
            }
          }
          .frame(maxWidth: .infinity, alignment: .leading)
          .accessibilityElement(children: .contain)
          .accessibilityLabel(field.label)
        }
      }
    }
    .padding(.vertical, WorkspaceDesign.spaceS)
    .frame(maxWidth: .infinity, alignment: .leading)
    .textSelection(.enabled)
  }

  private func fieldTitle(_ field: ProfileDisplayField) -> some View {
    Text(field.label)
      .font(.subheadline)
      .foregroundStyle(.secondary)
  }
}

private struct ProfileBulletLabelStyle: LabelStyle {
  func makeBody(configuration: Configuration) -> some View {
    HStack(alignment: .firstTextBaseline, spacing: 7) {
      configuration.icon
        .font(.system(size: 4))
        .foregroundStyle(.secondary)
      configuration.title
    }
  }
}
