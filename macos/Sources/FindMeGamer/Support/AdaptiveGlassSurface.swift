import SwiftUI

enum GlassSurfaceRole: CaseIterable, Equatable {
  case matchHero
  case batchOutreach
  case analyzeStatus
}

struct AdaptiveGlassSurface<Content: View>: View {
  let role: GlassSurfaceRole
  private let content: Content

  init(role: GlassSurfaceRole, @ViewBuilder content: () -> Content) {
    self.role = role
    self.content = content()
  }

  @ViewBuilder var body: some View {
    if #available(macOS 26.0, *) {
      content
        .padding()
        .glassEffect(.regular.interactive(), in: .rect(cornerRadius: 22))
    } else {
      GroupBox {
        content.padding(4)
      }
      .groupBoxStyle(.automatic)
    }
  }
}

struct AdaptiveGlassActionGroup<Content: View>: View {
  private let content: Content

  init(@ViewBuilder content: () -> Content) {
    self.content = content()
  }

  @ViewBuilder var body: some View {
    if #available(macOS 26.0, *) {
      GlassEffectContainer {
        content
      }
    } else {
      content
    }
  }
}
