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
      Color.secondary.opacity(0.12)

      if let image {
        Image(nsImage: image)
          .resizable()
          .scaledToFill()
      } else if isLoading {
        ProgressView()
          .controlSize(.small)
      } else {
        Image(systemName: fallbackSystemImage)
          .font(.title)
          .foregroundStyle(.secondary)
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
