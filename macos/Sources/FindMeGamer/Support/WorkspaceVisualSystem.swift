import AppKit
import FindMeGamerCore
import SwiftUI

struct WorkspacePageDescriptor: Equatable, Identifiable {
  let id: String
  let eyebrow: String
  let title: String
  let subtitle: String
}

enum WorkspacePageCopy {
  static let library = WorkspacePageDescriptor(
    id: "library",
    eyebrow: "PROFILE LIBRARY",
    title: "Profiles worth knowing.",
    subtitle: "A shared field guide to the games and creators your team has already understood.")
  static let match = WorkspacePageDescriptor(
    id: "match",
    eyebrow: "CREATOR DISCOVERY",
    title: "Find the signal in the noise.",
    subtitle: "Start with one analyzed game, then follow the strongest creator evidence.")
  static let outreach = WorkspacePageDescriptor(
    id: "outreach",
    eyebrow: "OUTREACH",
    title: "Conversations in motion.",
    subtitle: "Move from a good fit to a clear response without losing the thread.")
  static let settings = WorkspacePageDescriptor(
    id: "settings",
    eyebrow: "WORKSPACE",
    title: "Shape your workspace.",
    subtitle: "Personal preferences first; shared services and automation stay clearly marked.")

  static let all = [library, match, outreach, settings]
}

enum WorkspaceDesign {
  static let spaceXS: CGFloat = 6
  static let spaceS: CGFloat = 10
  static let spaceM: CGFloat = 16
  static let spaceL: CGFloat = 24
  static let spaceXL: CGFloat = 32
  static let pageHorizontalPadding: CGFloat = 28
  static let pageVerticalPadding: CGFloat = 24
  static let cardCornerRadius: CGFloat = 16
  static let featureCornerRadius: CGFloat = 22
  static let libraryGridMinimumWidth: CGFloat = 240
  static let libraryGridMaximumWidth: CGFloat = 340
}

enum WorkspaceTone: Equatable {
  case accent
  case success
  case warning
  case danger
  case neutral

  var color: Color {
    switch self {
    case .accent: .accentColor
    case .success: .green
    case .warning: .orange
    case .danger: .red
    case .neutral: .secondary
    }
  }
}

struct WorkspacePageHeader<Actions: View>: View {
  let descriptor: WorkspacePageDescriptor
  private let actions: Actions

  init(
    _ descriptor: WorkspacePageDescriptor,
    @ViewBuilder actions: () -> Actions
  ) {
    self.descriptor = descriptor
    self.actions = actions()
  }

  var body: some View {
    VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
      HStack(alignment: .bottom, spacing: WorkspaceDesign.spaceL) {
        VStack(alignment: .leading, spacing: WorkspaceDesign.spaceXS) {
          Text(descriptor.eyebrow)
            .font(.caption2.weight(.bold))
            .tracking(1.5)
            .foregroundStyle(Color.accentColor)

          Text(descriptor.title)
            .font(.system(.largeTitle, design: .serif, weight: .semibold))
            .tracking(-0.5)
            .accessibilityAddTraits(.isHeader)

          Text(descriptor.subtitle)
            .font(.callout)
            .foregroundStyle(.secondary)
            .lineLimit(2)
            .frame(maxWidth: 660, alignment: .leading)
        }

        Spacer(minLength: WorkspaceDesign.spaceM)
        actions
      }

      SignalTrail()
    }
    .accessibilityElement(children: .contain)
  }
}

extension WorkspacePageHeader where Actions == EmptyView {
  init(_ descriptor: WorkspacePageDescriptor) {
    self.init(descriptor) { EmptyView() }
  }
}

struct WorkspaceSectionHeader: View {
  let title: String
  let subtitle: String?
  let count: Int?

  init(_ title: String, subtitle: String? = nil, count: Int? = nil) {
    self.title = title
    self.subtitle = subtitle
    self.count = count
  }

  var body: some View {
    HStack(alignment: .firstTextBaseline, spacing: WorkspaceDesign.spaceS) {
      VStack(alignment: .leading, spacing: 3) {
        Text(title)
          .font(.title3.weight(.semibold))
          .accessibilityAddTraits(.isHeader)
        if let subtitle {
          Text(subtitle)
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }
      if let count {
        Text(count, format: .number)
          .font(.caption.weight(.semibold).monospacedDigit())
          .foregroundStyle(.secondary)
          .padding(.horizontal, 8)
          .padding(.vertical, 3)
          .background(Color.secondary.opacity(0.1), in: Capsule())
      }
      Spacer()
    }
  }
}

struct SignalTrail: View {
  var body: some View {
    GeometryReader { proxy in
      ZStack(alignment: .leading) {
        LinearGradient(
          colors: [Color.accentColor.opacity(0.7), Color.cyan.opacity(0.35), .clear],
          startPoint: .leading,
          endPoint: .trailing
        )
        .frame(height: 1)

        Circle()
          .fill(Color.accentColor)
          .frame(width: 6, height: 6)
          .offset(x: min(proxy.size.width * 0.58, 520))

        Circle()
          .fill(Color.cyan)
          .frame(width: 4, height: 4)
          .offset(x: min(proxy.size.width * 0.72, 650))
      }
    }
    .frame(height: 6)
    .accessibilityHidden(true)
  }
}

struct SignalMark: View {
  var body: some View {
    ZStack {
      Circle()
        .stroke(Color.accentColor.opacity(0.9), lineWidth: 2)
        .frame(width: 24, height: 15)
        .rotationEffect(.degrees(-18))
      Capsule()
        .fill(
          LinearGradient(
            colors: [Color.accentColor, Color.cyan],
            startPoint: .leading,
            endPoint: .trailing)
        )
        .frame(width: 30, height: 2)
        .rotationEffect(.degrees(-28))
      Circle()
        .fill(Color.cyan)
        .frame(width: 5, height: 5)
        .offset(x: 11, y: -7)
    }
    .frame(width: 34, height: 28)
    .accessibilityHidden(true)
  }
}

enum WorkspaceSurfaceStyle: Equatable {
  case quiet
  case card
  case elevated
}

struct WorkspaceSurface<Content: View>: View {
  let style: WorkspaceSurfaceStyle
  private let content: Content

  init(style: WorkspaceSurfaceStyle = .card, @ViewBuilder content: () -> Content) {
    self.style = style
    self.content = content()
  }

  var body: some View {
    content
      .background(backgroundShape)
      .overlay(borderShape)
      .shadow(
        color: style == .elevated ? Color.black.opacity(0.12) : .clear,
        radius: style == .elevated ? 18 : 0,
        y: style == .elevated ? 8 : 0)
  }

  private var radius: CGFloat {
    style == .elevated ? WorkspaceDesign.featureCornerRadius : WorkspaceDesign.cardCornerRadius
  }

  private var backgroundShape: some View {
    RoundedRectangle(cornerRadius: radius, style: .continuous)
      .fill(
        style == .quiet
          ? Color.secondary.opacity(0.045)
          : Color(nsColor: .controlBackgroundColor).opacity(0.88))
  }

  private var borderShape: some View {
    RoundedRectangle(cornerRadius: radius, style: .continuous)
      .strokeBorder(Color.primary.opacity(style == .quiet ? 0.06 : 0.1), lineWidth: 1)
  }
}

struct WorkspaceStatusLozenge: View {
  let title: String
  let systemImage: String
  let tone: WorkspaceTone

  var body: some View {
    Label(title, systemImage: systemImage)
      .font(.caption2.weight(.semibold))
      .foregroundStyle(tone.color)
      .padding(.horizontal, 8)
      .padding(.vertical, 5)
      .background(tone.color.opacity(0.11), in: Capsule())
      .accessibilityElement(children: .combine)
  }
}

struct WorkspaceCanvasModifier: ViewModifier {
  func body(content: Content) -> some View {
    content
      .background {
        ZStack {
          Color(nsColor: .windowBackgroundColor)
          RadialGradient(
            colors: [Color.accentColor.opacity(0.075), .clear],
            center: .topTrailing,
            startRadius: 0,
            endRadius: 620)
        }
        .ignoresSafeArea()
      }
  }
}

extension View {
  func workspaceCanvas() -> some View {
    modifier(WorkspaceCanvasModifier())
  }
}

struct MatchCandidatePreviewPolicy: Equatable {
  let primaryReason: String?
  let additionalReasonCount: Int

  init(reasons: [String]) {
    primaryReason = reasons.first
    additionalReasonCount = max(reasons.count - 1, 0)
  }
}

struct CampaignMetricPresentation: Equatable, Identifiable {
  var id: String { label }
  let label: String
  let value: String
  let systemImage: String
  let tone: WorkspaceTone
  let isPrimary: Bool

  static func items(_ metrics: CampaignMetrics) -> [CampaignMetricPresentation] {
    [
      .init(
        label: "Sent", value: metrics.sentCreators.formatted(),
        systemImage: "paperplane.fill", tone: .accent, isPrimary: true),
      .init(
        label: "Response Rate",
        value: metrics.responseRate.formatted(.percent.precision(.fractionLength(0))),
        systemImage: "arrowshape.turn.up.left.fill", tone: .accent, isPrimary: true),
      .init(
        label: "Accepted", value: metrics.accepted.formatted(),
        systemImage: "checkmark.circle.fill", tone: .success, isPrimary: true),
      .init(
        label: "Declined", value: metrics.declined.formatted(),
        systemImage: "xmark.circle.fill", tone: .neutral, isPrimary: false),
      .init(
        label: "No Response", value: metrics.noResponse.formatted(),
        systemImage: "clock.fill", tone: .neutral, isPrimary: false),
      .init(
        label: "Failed", value: metrics.failed.formatted(),
        systemImage: "exclamationmark.triangle.fill", tone: .danger, isPrimary: false),
    ]
  }
}

struct CampaignMetricGrid: View {
  let metrics: CampaignMetrics
  var compact = false

  var body: some View {
    LazyVGrid(
      columns: [
        GridItem(.adaptive(minimum: compact ? 126 : 132), spacing: WorkspaceDesign.spaceS)
      ],
      alignment: .leading,
      spacing: WorkspaceDesign.spaceS
    ) {
      ForEach(CampaignMetricPresentation.items(metrics)) { metric in
        VStack(alignment: .leading, spacing: 5) {
          Label(metric.label, systemImage: metric.systemImage)
            .font(.caption)
            .foregroundStyle(metric.tone.color)
            .lineLimit(2)
          Text(metric.value)
            .font((metric.isPrimary ? Font.title3 : Font.headline).monospacedDigit())
            .fontWeight(metric.isPrimary ? .semibold : .regular)
        }
        .frame(maxWidth: .infinity, minHeight: compact ? 48 : 56, alignment: .leading)
        .padding(compact ? 9 : 12)
        .background(
          metric.tone.color.opacity(metric.isPrimary ? 0.08 : 0.035),
          in: RoundedRectangle(cornerRadius: 10, style: .continuous)
        )
        .accessibilityElement(children: .combine)
      }
    }
  }
}
