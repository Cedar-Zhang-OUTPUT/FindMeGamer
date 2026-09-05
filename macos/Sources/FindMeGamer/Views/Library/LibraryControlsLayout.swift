import SwiftUI

enum LibraryControlsArrangement: Equatable {
  case row, twoRows, stacked
}

struct LibraryControlsLayoutPlan {
  static let columnSpacing: CGFloat = 16
  static let rowSpacing: CGFloat = 10
  static let minimumSearchWidth: CGFloat = 160

  let arrangement: LibraryControlsArrangement
  let width: CGFloat
  // The order never changes: profile type, search, favorites.
  let widths: [CGFloat]
  let horizontalOffsets: [CGFloat]

  init(availableWidth: CGFloat, pickerWidth: CGFloat, favoritesWidth: CGFloat) {
    width = max(0, availableWidth)
    let picker = min(max(0, pickerWidth), width)
    let favorites = min(max(0, favoritesWidth), width)
    let controlsWidth = picker + favorites

    if width >= controlsWidth + Self.minimumSearchWidth + 2 * Self.columnSpacing {
      arrangement = .row
      widths = [
        picker,
        min(LibraryLayout.searchMaximumWidth, width - controlsWidth - 2 * Self.columnSpacing),
        favorites,
      ]
      horizontalOffsets = [0, picker + Self.columnSpacing, width - favorites]
    } else if width >= controlsWidth + Self.rowSpacing {
      arrangement = .twoRows
      widths = [picker, width, favorites]
      horizontalOffsets = [0, 0, width - favorites]
    } else {
      arrangement = .stacked
      widths = [width, width, width]
      horizontalOffsets = [0, 0, 0]
    }
  }

  func height(for heights: [CGFloat]) -> CGFloat {
    switch arrangement {
    case .row:
      heights.max() ?? 0
    case .twoRows:
      max(heights[0], heights[2]) + Self.rowSpacing + heights[1]
    case .stacked:
      heights.reduce(0, +) + 2 * Self.rowSpacing
    }
  }

  func verticalOffsets(for heights: [CGFloat]) -> [CGFloat] {
    switch arrangement {
    case .row:
      let rowHeight = heights.max() ?? 0
      return heights.map { (rowHeight - $0) / 2 }
    case .twoRows:
      let firstRowHeight = max(heights[0], heights[2])
      return [
        (firstRowHeight - heights[0]) / 2,
        firstRowHeight + Self.rowSpacing,
        (firstRowHeight - heights[2]) / 2,
      ]
    case .stacked:
      return [0, heights[0] + Self.rowSpacing, heights[0] + heights[1] + 2 * Self.rowSpacing]
    }
  }
}

/// Repositions the same three controls rather than rebuilding a focused search field.
struct LibraryControlsLayout: Layout {
  func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
    guard subviews.count == 3 else { return .zero }
    let measured = measure(width: proposal.width, subviews: subviews)
    return CGSize(width: measured.plan.width, height: measured.plan.height(for: measured.heights))
  }

  func placeSubviews(
    in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()
  ) {
    guard subviews.count == 3 else { return }
    let measured = measure(width: bounds.width, subviews: subviews)
    let verticalOffsets = measured.plan.verticalOffsets(for: measured.heights)
    for index in subviews.indices {
      subviews[index].place(
        at: CGPoint(
          x: bounds.minX + measured.plan.horizontalOffsets[index],
          y: bounds.minY + verticalOffsets[index]),
        anchor: .topLeading,
        proposal: ProposedViewSize(
          width: measured.plan.widths[index], height: measured.heights[index]))
    }
  }

  private func measure(width proposedWidth: CGFloat?, subviews: Subviews)
    -> (plan: LibraryControlsLayoutPlan, heights: [CGFloat])
  {
    let pickerWidth = subviews[0].sizeThatFits(.unspecified).width
    let favoritesWidth = subviews[2].sizeThatFits(.unspecified).width
    let idealWidth =
      pickerWidth + favoritesWidth + LibraryLayout.searchMaximumWidth
      + 2 * LibraryControlsLayoutPlan.columnSpacing
    let width = proposedWidth.flatMap { $0.isFinite ? $0 : nil } ?? idealWidth
    let plan = LibraryControlsLayoutPlan(
      availableWidth: width, pickerWidth: pickerWidth, favoritesWidth: favoritesWidth)
    let heights = subviews.indices.map {
      subviews[$0].sizeThatFits(ProposedViewSize(width: plan.widths[$0], height: nil)).height
    }
    return (plan, heights)
  }
}
