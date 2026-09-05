import FindMeGamerCore
import SwiftUI

/// Color describes the kind of information, never a synthetic score or verdict.
enum ProfileStoryTone: Equatable {
  case identity, audience, opportunity, caution

  var color: Color {
    switch self {
    case .identity: StudioPalette.coral
    case .audience: StudioPalette.blue
    case .opportunity: StudioPalette.mint
    case .caution: StudioPalette.amber
    }
  }

  static func forField(_ label: String) -> Self {
    switch label {
    case "Audience", "Target Audience": .audience
    case "Promotion Fit", "Content Hooks", "Suitable Game Types", "Key Selling Points": .opportunity
    case "Brand Safety", "Collaboration Risks", "Promotion Risks": .caution
    default: .identity
    }
  }

  static func symbol(for label: String) -> String {
    switch label {
    case "Audience", "Target Audience": "person.2.fill"
    case "Promotion Fit", "Suitable Game Types": "sparkles"
    case "Content Hooks", "Key Selling Points": "lightbulb.fill"
    case "Brand Safety": "checkmark.shield"
    case "Collaboration Risks", "Promotion Risks": "exclamationmark.bubble"
    case "Core Gameplay Loop": "arrow.2.circlepath"
    case "Content Focus": "play.rectangle.fill"
    default: "text.quote"
    }
  }

  static func usesTopicChips(for field: ProfileDisplayField) -> Bool {
    field.label == "Content Focus" && field.values.count > 1
  }
}

/// Small, source-backed facts. Missing values stay missing and are never
/// replaced by calculated estimates, rankings, or AI-inferred metrics.
struct ProfileMetricPresentation: Equatable {
  let label: String
  let value: String

  static func sourceMetrics(
    fields: [ProfileDisplayField], type: ProfileType
  ) -> [Self] {
    let labels =
      type == .creator
      ? ["Subscribers", "Average Views", "Public Videos"]
      : ["Release Date", "Review Summary", "Recommendations"]
    return labels.compactMap { label in
      guard let field = fields.first(where: { $0.label == label }),
        field.values.count == 1,
        let raw = field.values.first,
        !raw.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
        raw != "Not available"
      else { return nil }
      // Keep precise counts rather than converting them to a rounded K/M badge.
      let value = Int(raw).map { $0.formatted(.number) } ?? raw
      return Self(label: label, value: value)
    }
  }
}

struct ProfileMetricStrip: View {
  let metrics: [ProfileMetricPresentation]

  var body: some View {
    if !metrics.isEmpty {
      LazyVGrid(
        columns: [GridItem(.adaptive(minimum: 130), spacing: 16, alignment: .leading)],
        alignment: .leading, spacing: 14
      ) {
        ForEach(Array(metrics.enumerated()), id: \.offset) { _, metric in
          VStack(alignment: .leading, spacing: 4) {
            Text(metric.value)
              .font(.system(.title3, design: .rounded, weight: .bold))
              .foregroundStyle(StudioPalette.ink)
              .textSelection(.enabled)
            Text(metric.label)
              .font(.caption)
              .foregroundStyle(.secondary)
          }
          .frame(maxWidth: .infinity, alignment: .leading)
        }
      }
      .accessibilityElement(children: .contain)
      .accessibilityLabel("Source facts")
    }
  }
}

struct ProfileInsightCard: View {
  let field: ProfileDisplayField
  private var tone: ProfileStoryTone { .forField(field.label) }

  var body: some View {
    VStack(alignment: .leading, spacing: 7) {
      HStack(spacing: 9) {
        Image(systemName: ProfileStoryTone.symbol(for: field.label))
          .font(.system(size: 13, weight: .semibold))
          .foregroundStyle(tone.color)
          .accessibilityHidden(true)
        Text(field.label)
          .font(.subheadline.weight(.semibold))
          .accessibilityAddTraits(.isHeader)
      }
      if ProfileStoryTone.usesTopicChips(for: field) {
        LazyVGrid(
          columns: [GridItem(.adaptive(minimum: 90), spacing: 7, alignment: .leading)],
          alignment: .leading, spacing: 7
        ) {
          ForEach(Array(field.values.enumerated()), id: \.offset) { _, value in
            Text(value)
              .font(.caption.weight(.medium))
              .foregroundStyle(tone.color)
              .fixedSize(horizontal: false, vertical: true)
              .padding(.horizontal, 11)
              .padding(.vertical, 7)
              .background(tone.color.opacity(0.09), in: Capsule())
          }
        }
      } else {
        VStack(alignment: .leading, spacing: 9) {
          ForEach(Array(field.values.enumerated()), id: \.offset) { _, value in
            HStack(alignment: .firstTextBaseline, spacing: 8) {
              if field.values.count > 1 {
                Circle()
                  .fill(tone.color.opacity(0.65))
                  .frame(width: 4, height: 4)
                  .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] }
                  .accessibilityHidden(true)
              }
              Text(value)
                .font(.callout)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)
            }
          }
        }
      }
      if let annotation = field.annotation {
        Text(annotation)
          .font(.caption2)
          .foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
      }
    }
    .frame(maxWidth: .infinity, alignment: .topLeading)
    .textSelection(.enabled)
  }
}

struct ProfileEvidenceSection<Content: View>: View {
  let title: String
  var subtitle: String? = nil
  let symbol: String
  let tone: ProfileStoryTone
  @ViewBuilder let content: () -> Content

  var body: some View {
    DisclosureGroup {
      content().padding(.top, 12)
    } label: {
      HStack(spacing: 10) {
        Image(systemName: symbol)
          .font(.system(size: 14, weight: .medium))
          .foregroundStyle(tone.color)
          .frame(width: 34, height: 34)
          .background(tone.color.opacity(0.1), in: RoundedRectangle(cornerRadius: 11))
          .accessibilityHidden(true)
        Text(title).font(.subheadline.weight(.semibold))
        Spacer(minLength: 8)
        if let subtitle {
          Text(subtitle)
            .font(.caption)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        }
      }
      .padding(.vertical, 5)
    }
    .padding(14)
    .background(tone.color.opacity(0.035), in: RoundedRectangle(cornerRadius: 17))
  }
}
