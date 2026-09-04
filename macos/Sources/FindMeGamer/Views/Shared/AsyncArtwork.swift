import AppKit
import Foundation
import SwiftUI

enum ArtworkURLPolicy {
  static func validated(_ url: URL?) -> URL? {
    guard let url,
      let scheme = url.scheme?.lowercased(),
      scheme == "http" || scheme == "https",
      url.host != nil
    else {
      return nil
    }
    return url
  }
}

enum ArtworkLoader {
  static func makeConfiguration() -> URLSessionConfiguration {
    let configuration = URLSessionConfiguration.default
    configuration.urlCache = URLCache.shared
    configuration.requestCachePolicy = .useProtocolCachePolicy
    return configuration
  }

  static let session = URLSession(configuration: makeConfiguration())
}

struct AsyncArtwork: View {
  let url: URL?
  let fallbackSystemImage: String

  @State private var image: NSImage?
  @State private var isLoading = false
  @State private var requestID = UUID()

  var body: some View {
    ZStack {
      ArtworkPlaceholder(systemImage: fallbackSystemImage)

      if let image {
        Image(nsImage: image)
          .resizable()
          .scaledToFill()
      } else if isLoading {
        ProgressView()
          .controlSize(.small)
      }
    }
    .clipped()
    .task(id: url) {
      await load()
    }
  }

  @MainActor
  private func load() async {
    let requestID = UUID()
    self.requestID = requestID
    image = nil

    guard let url = ArtworkURLPolicy.validated(url) else {
      isLoading = false
      return
    }

    isLoading = true
    do {
      let request = URLRequest(url: url, cachePolicy: .useProtocolCachePolicy)
      let (data, response) = try await ArtworkLoader.session.data(for: request)
      try Task.checkCancellation()
      guard self.requestID == requestID,
        let response = response as? HTTPURLResponse,
        (200..<300).contains(response.statusCode),
        let decoded = NSImage(data: data)
      else {
        if self.requestID == requestID { isLoading = false }
        return
      }
      image = decoded
      isLoading = false
    } catch {
      guard self.requestID == requestID else { return }
      image = nil
      isLoading = false
    }
  }
}

private struct ArtworkPlaceholder: View {
  let systemImage: String

  var body: some View {
    GeometryReader { proxy in
      ZStack {
        LinearGradient(
          colors: [
            Color.accentColor.opacity(0.2),
            Color.cyan.opacity(0.08),
            Color.secondary.opacity(0.1),
          ],
          startPoint: .topLeading,
          endPoint: .bottomTrailing)

        Circle()
          .fill(Color.accentColor.opacity(0.1))
          .frame(width: proxy.size.width * 0.72)
          .blur(radius: 1)
          .offset(x: proxy.size.width * 0.3, y: -proxy.size.height * 0.28)

        Circle()
          .stroke(Color.cyan.opacity(0.22), lineWidth: 1)
          .frame(width: min(proxy.size.width, proxy.size.height) * 0.58)
          .offset(x: -proxy.size.width * 0.26, y: proxy.size.height * 0.22)

        Image(systemName: systemImage)
          .font(.system(size: min(proxy.size.width, proxy.size.height) * 0.25, weight: .medium))
          .symbolRenderingMode(.hierarchical)
          .foregroundStyle(Color.primary.opacity(0.5))
      }
    }
    .accessibilityHidden(true)
  }
}
