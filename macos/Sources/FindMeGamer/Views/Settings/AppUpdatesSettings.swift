import SwiftUI

struct AppUpdatesSettings: View {
  @Bindable var checker: AppUpdateChecker

  var body: some View {
    Section("Find Me Gamer") {
      LabeledContent("Installed version", value: checker.installedVersion ?? "Development build")

      if let release = checker.availableRelease {
        Label("Version \(release.version) is available", systemImage: "arrow.down.circle.fill")
          .font(.headline)
          .foregroundStyle(StudioPalette.blue)
          .accessibilityIdentifier("app.update.new-version")
        Link("View release & download", destination: release.releasePageURL)
          .buttonStyle(.borderedProminent)
          .accessibilityIdentifier("app.update.download")
        Text("GitHub access is required. Download and replace the app manually.")
          .font(.callout)
          .foregroundStyle(.secondary)
      }

      status
    }

    Section {
      Button(checker.isChecking ? "Checking…" : "Check for Updates") {
        Task { await checker.check() }
      }
      .disabled(checker.isChecking || !checker.sourceEnabled || checker.state == .developmentBuild)
      .accessibilityIdentifier("app.update.check")

      Toggle("Automatically check for updates", isOn: $checker.automaticallyChecks)
        .disabled(!checker.sourceEnabled)

      if let lastChecked = checker.lastCheckedAt {
        LabeledContent(
          "Last checked", value: lastChecked.formatted(date: .abbreviated, time: .shortened)
        )
        .foregroundStyle(.secondary)
      }

      Link("All releases on GitHub", destination: AppUpdateFeed.releasesURL)
    }
  }

  @ViewBuilder private var status: some View {
    switch checker.state {
    case .idle:
      EmptyView()
    case .checking:
      ProgressView("Checking for updates…").controlSize(.small)
    case .checked:
      if checker.availableRelease == nil {
        Label("You’re up to date", systemImage: "checkmark.circle")
          .foregroundStyle(.secondary)
          .accessibilityIdentifier("app.update.current")
      }
    case .developmentBuild:
      Text("This development build has no verifiable app version.")
        .foregroundStyle(.secondary)
    case .disabled:
      Text("The update service is not enabled for this build.")
        .foregroundStyle(.secondary)
    case .failed(let message):
      Label(message, systemImage: "exclamationmark.triangle")
        .foregroundStyle(StudioPalette.amber)
        .accessibilityIdentifier("app.update.error")
    }
  }
}

struct AppUpdatesWindow: View {
  @Bindable var checker: AppUpdateChecker

  var body: some View {
    Form {
      AppUpdatesSettings(checker: checker)
    }
    .formStyle(.grouped)
    .frame(minWidth: 440, idealWidth: 480, minHeight: 330, idealHeight: 420)
    .modifier(AppearancePreferences())
  }
}

struct AppUpdateCommands: Commands {
  let checker: AppUpdateChecker
  @Environment(\.openWindow) private var openWindow

  var body: some Commands {
    CommandGroup(after: .appInfo) {
      Button("Check for Updates…") {
        openWindow(id: "app-updates")
        Task { await checker.check() }
      }
      .disabled(checker.isChecking)
    }
  }
}
