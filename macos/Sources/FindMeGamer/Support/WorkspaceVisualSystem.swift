import AppKit
import FindMeGamerCore
import SwiftUI

struct WorkspacePageDescriptor: Equatable, Identifiable {
  let id: String
  let title: String
}

enum WorkspacePageCopy {
  static let discover = WorkspacePageDescriptor(id: "discover", title: "Discover")
  static let library = WorkspacePageDescriptor(id: "library", title: "Library")
  static let match = WorkspacePageDescriptor(id: "match", title: "Match")
  static let outreach = WorkspacePageDescriptor(id: "outreach", title: "Outreach")
  static let settings = WorkspacePageDescriptor(id: "settings", title: "Settings")

  static let all = [discover, match, outreach, library, settings]
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
    case .accent: StudioPalette.blue
    case .success: StudioPalette.mint
    case .warning: StudioPalette.amber
    case .danger: StudioPalette.coral
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
    ViewThatFits(in: .horizontal) {
      HStack(alignment: .center, spacing: WorkspaceDesign.spaceL) {
        heading
        Spacer(minLength: WorkspaceDesign.spaceM)
        actions.fixedSize(horizontal: true, vertical: false)
      }
      VStack(alignment: .leading, spacing: WorkspaceDesign.spaceM) {
        heading
        actions
      }
    }
    .fixedSize(horizontal: false, vertical: true)
    .frame(maxWidth: .infinity, alignment: .leading)
    .accessibilityElement(children: .contain)
  }

  private var heading: some View {
    Text(descriptor.title)
      .font(.system(size: 25, weight: .bold, design: .rounded))
      .foregroundStyle(StudioPalette.ink)
      .tracking(-0.6)
      .fixedSize(horizontal: false, vertical: true)
      .accessibilityAddTraits(.isHeader)
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
          .font(.headline)
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
        color: style == .quiet
          ? .clear : StudioPalette.ink.opacity(style == .elevated ? 0.09 : 0.035),
        radius: style == .elevated ? 18 : 8,
        x: 0, y: style == .elevated ? 8 : 3)
  }

  private var radius: CGFloat {
    style == .elevated ? WorkspaceDesign.featureCornerRadius : WorkspaceDesign.cardCornerRadius
  }

  private var backgroundShape: some View {
    RoundedRectangle(cornerRadius: radius, style: .continuous)
      .fill(
        style == .quiet
          ? StudioPalette.blue.opacity(0.045)
          : StudioPalette.surface)
  }

  private var borderShape: some View {
    RoundedRectangle(cornerRadius: radius, style: .continuous)
      .strokeBorder(StudioPalette.line.opacity(style == .quiet ? 0 : 0.65), lineWidth: 0.7)
      .allowsHitTesting(false)
  }
}

struct WorkspaceStatusLozenge: View {
  let title: String
  let systemImage: String
  let tone: WorkspaceTone

  var body: some View {
    Label(title, systemImage: systemImage)
      .font(.caption.weight(.medium))
      .foregroundStyle(tone.color)
      .padding(.horizontal, 8)
      .padding(.vertical, 5)
      .background(tone.color.opacity(0.075), in: Capsule())
      .accessibilityElement(children: .combine)
  }
}

struct WorkspaceCanvasModifier: ViewModifier {
  func body(content: Content) -> some View {
    content
      .background {
        StudioPalette.canvas
          .overlay(alignment: .topTrailing) {
            RadialGradient(
              colors: [StudioPalette.blue.opacity(0.035), .clear],
              center: .topTrailing, startRadius: 0, endRadius: 620)
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
          Text(metric.label)
            .font(.caption)
            .foregroundStyle(.secondary)
            .lineLimit(2)
          Text(metric.value)
            .font((metric.isPrimary ? Font.title3 : Font.headline).monospacedDigit())
            .fontWeight(metric.isPrimary ? .semibold : .regular)
        }
        .frame(maxWidth: .infinity, minHeight: compact ? 48 : 56, alignment: .leading)
        .padding(compact ? 9 : 12)
        .accessibilityElement(children: .combine)
      }
    }
  }
}
