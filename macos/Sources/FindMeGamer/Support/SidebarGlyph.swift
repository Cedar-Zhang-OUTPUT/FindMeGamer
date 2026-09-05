import AppKit
import FindMeGamerCore
import SwiftUI

enum SidebarGlyph: String, CaseIterable, Hashable {
  case libraryMatrix
  case matchOrbit
  case outreachSignal
  case settingsControls

  init(destination: AppDestination) {
    switch destination {
    case .library: self = .libraryMatrix
    case .match: self = .matchOrbit
    case .outreach: self = .outreachSignal
    case .settings: self = .settingsControls
    }
  }
}

enum SidebarGlyphContrastMode: Equatable {
  case activeSelection
  case inactiveSelection
  case unselected
}

enum SidebarGlyphContrastPolicy {
  static func mode(isSelected: Bool, isControlActive: Bool) -> SidebarGlyphContrastMode {
    guard isSelected else { return .unselected }
    return isControlActive ? .activeSelection : .inactiveSelection
  }
}

struct SidebarDestinationIcon: View {
  @Environment(\.controlActiveState) private var controlActiveState
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  let glyph: SidebarGlyph
  let isSelected: Bool

  var body: some View {
    let blend = WorkspaceMotionPolicy.selectionBlend(isSelected: isSelected)

    ZStack {
      glyphCanvas(selected: false)
        .opacity(blend.unselectedOpacity)
      glyphCanvas(selected: true)
        .opacity(blend.selectedOpacity)
    }
    .frame(width: 20, height: 20)
    .scaleEffect(
      isSelected
        ? 1
        : WorkspaceMotionPolicy.profile(
          for: .selectionFeedback,
          reduceMotion: reduceMotion
        ).inactiveScale
    )
    .animation(
      WorkspaceMotionPolicy.animation(for: .selectionFeedback, reduceMotion: reduceMotion),
      value: isSelected
    )
    .accessibilityHidden(true)
  }

  private func glyphCanvas(selected: Bool) -> some View {
    Canvas { context, size in
      let scale = min(size.width, size.height) / 20
      context.scaleBy(x: scale, y: scale)

      let colors = colors(
        for: SidebarGlyphContrastPolicy.mode(
          isSelected: selected,
          isControlActive: controlActiveState != .inactive))
      let stroke = StrokeStyle(lineWidth: 1.55, lineCap: .round, lineJoin: .round)

      switch glyph {
      case .libraryMatrix:
        drawLibraryMatrix(
          in: &context,
          lineColor: colors.line,
          detailColor: colors.detail,
          quietColor: colors.quiet,
          stroke: stroke,
          isSelected: selected)
      case .matchOrbit:
        drawMatchOrbit(
          in: &context,
          lineColor: colors.line,
          detailColor: colors.detail,
          quietColor: colors.quiet,
          stroke: stroke)
      case .outreachSignal:
        drawOutreachSignal(
          in: &context,
          lineColor: colors.line,
          detailColor: colors.detail,
          quietColor: colors.quiet,
          stroke: stroke,
          isSelected: selected)
      case .settingsControls:
        drawSettingsControls(
          in: &context,
          lineColor: colors.line,
          detailColor: colors.detail,
          quietColor: colors.quiet,
          stroke: stroke)
      }
    }
  }

  private func colors(for mode: SidebarGlyphContrastMode) -> (
    line: Color, detail: Color, quiet: Color
  ) {
    switch mode {
    case .activeSelection:
      let selectedText = Color(nsColor: .alternateSelectedControlTextColor)
      return (selectedText, selectedText.opacity(0.82), selectedText.opacity(0.32))
    case .inactiveSelection:
      return (Color.primary.opacity(0.78), Color.accentColor, Color.primary.opacity(0.2))
    case .unselected:
      return (Color.primary.opacity(0.78), Color.accentColor, Color.primary.opacity(0.2))
    }
  }

  private func drawLibraryMatrix(
    in context: inout GraphicsContext,
    lineColor: Color,
    detailColor: Color,
    quietColor: Color,
    stroke: StrokeStyle,
    isSelected: Bool
  ) {
    let cells = [
      CGRect(x: 2.25, y: 2.25, width: 6.25, height: 6.25),
      CGRect(x: 11.5, y: 2.25, width: 6.25, height: 6.25),
      CGRect(x: 2.25, y: 11.5, width: 6.25, height: 6.25),
      CGRect(x: 11.5, y: 11.5, width: 6.25, height: 6.25),
    ]

    for (index, rect) in cells.enumerated() {
      let cell = Path(roundedRect: rect, cornerRadius: 1.8)
      if index == 1 {
        context.fill(cell, with: .color(detailColor.opacity(isSelected ? 0.72 : 0.2)))
      }
      context.stroke(
        cell,
        with: .color(index == 1 ? detailColor : (index == 2 ? quietColor : lineColor)),
        style: stroke)
    }
  }

  private func drawMatchOrbit(
    in context: inout GraphicsContext,
    lineColor: Color,
    detailColor: Color,
    quietColor: Color,
    stroke: StrokeStyle
  ) {
    let orbit = Path(ellipseIn: CGRect(x: 2, y: 5.1, width: 16, height: 9.8))
    context.stroke(
      orbit,
      with: .color(quietColor),
      style: StrokeStyle(lineWidth: 1.05, dash: [2.2, 2.2]))

    var connection = Path()
    connection.move(to: CGPoint(x: 5.1, y: 13.9))
    connection.addCurve(
      to: CGPoint(x: 14.9, y: 6.1),
      control1: CGPoint(x: 7.8, y: 14.1),
      control2: CGPoint(x: 12.1, y: 5.9))
    context.stroke(connection, with: .color(lineColor), style: stroke)

    let firstNode = Path(ellipseIn: CGRect(x: 2.55, y: 11.35, width: 5.1, height: 5.1))
    let secondNode = Path(ellipseIn: CGRect(x: 12.35, y: 3.55, width: 5.1, height: 5.1))
    context.fill(firstNode, with: .color(lineColor))
    context.fill(secondNode, with: .color(detailColor))
  }

  private func drawOutreachSignal(
    in context: inout GraphicsContext,
    lineColor: Color,
    detailColor: Color,
    quietColor: Color,
    stroke: StrokeStyle,
    isSelected: Bool
  ) {
    var signal = Path()
    signal.move(to: CGPoint(x: 2.25, y: 14.6))
    signal.addCurve(
      to: CGPoint(x: 7.2, y: 9.65),
      control1: CGPoint(x: 4.95, y: 14.5),
      control2: CGPoint(x: 7.1, y: 12.35))
    context.stroke(signal, with: .color(quietColor), style: stroke)

    var plane = Path()
    plane.move(to: CGPoint(x: 5.7, y: 9.9))
    plane.addLine(to: CGPoint(x: 17.65, y: 3.15))
    plane.addLine(to: CGPoint(x: 13.1, y: 16.9))
    plane.addLine(to: CGPoint(x: 10.25, y: 11.2))
    plane.closeSubpath()
    context.fill(plane, with: .color(detailColor.opacity(isSelected ? 0.54 : 0.16)))
    context.stroke(plane, with: .color(lineColor), style: stroke)

    var route = Path()
    route.move(to: CGPoint(x: 10.25, y: 11.2))
    route.addLine(to: CGPoint(x: 17.65, y: 3.15))
    context.stroke(route, with: .color(detailColor), style: stroke)
  }

  private func drawSettingsControls(
    in context: inout GraphicsContext,
    lineColor: Color,
    detailColor: Color,
    quietColor: Color,
    stroke: StrokeStyle
  ) {
    let rails: [(CGFloat, CGFloat)] = [(5, 6.2), (10, 13.5), (15, 8.4)]

    for (index, rail) in rails.enumerated() {
      var path = Path()
      path.move(to: CGPoint(x: 2.4, y: rail.0))
      path.addLine(to: CGPoint(x: 17.6, y: rail.0))
      context.stroke(path, with: .color(index == 1 ? quietColor : lineColor), style: stroke)

      let knobRect = CGRect(x: rail.1 - 2.15, y: rail.0 - 2.15, width: 4.3, height: 4.3)
      let knob = Path(ellipseIn: knobRect)
      context.fill(knob, with: .color(index == 1 ? detailColor : lineColor))
    }
  }
}
