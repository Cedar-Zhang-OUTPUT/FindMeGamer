import AppKit
import Foundation
import SwiftUI
import Testing

@testable import FindMeGamer

@Suite @MainActor struct MatchInkContrastTests {
  @Test func selectorMainLabelHasReadableContrast() throws {
    let ratio = try contrast(MatchInkControlColors.text, against: MatchInkControlColors.surface)
    #expect(ratio >= 4.5)
  }

  @Test func selectorSecondaryLabelHasReadableContrast() throws {
    let ratio = try contrast(
      MatchInkControlColors.secondaryText, against: MatchInkControlColors.surface)
    #expect(ratio >= 4.5)
  }

  @Test func primaryActionWhiteLabelHasReadableContrast() throws {
    let ratio = try contrast(.white, against: MatchInkControlColors.actionBackground)
    #expect(ratio >= 4.5)
  }

  private func contrast(_ foreground: Color, against background: Color) throws -> Double {
    let first = try luminance(foreground)
    let second = try luminance(background)
    return (max(first, second) + 0.05) / (min(first, second) + 0.05)
  }

  private func luminance(_ color: Color) throws -> Double {
    let rgb = try #require(NSColor(color).usingColorSpace(.sRGB))
    func linear(_ component: CGFloat) -> Double {
      let value = Double(component)
      return value <= 0.04045 ? value / 12.92 : pow((value + 0.055) / 1.055, 2.4)
    }
    return 0.2126 * linear(rgb.redComponent) + 0.7152 * linear(rgb.greenComponent)
      + 0.0722 * linear(rgb.blueComponent)
  }
}
