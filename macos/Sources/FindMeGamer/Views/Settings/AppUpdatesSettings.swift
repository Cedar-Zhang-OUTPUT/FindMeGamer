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
        Link("Download on GitHub", destination: release.releasePageURL)
          .buttonStyle(.borderedProminent)
          .accessibilityIdentifier("app.update.download")
        Text("Manual installation · GitHub access required")
          .font(.callout)
          .foregroundStyle(.secondary)
          .help(
            "Download the disk image, then replace the installed app. Updates are not installed automatically."
          )
      }

      status
    }

    Section {
      Button {
        Task { await checker.check() }
      } label: {
        HStack(spacing: 8) {
          if checker.isChecking { ProgressView().controlSize(.mini) }
          Text(checker.isChecking ? "Checking…" : "Check for Updates")
        }
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
    case .idle, .checking:
      EmptyView()
    case .checked:
      if checker.availableRelease == nil {
        Label("You’re up to date", systemImage: "checkmark.circle")
          .foregroundStyle(.secondary)
          .accessibilityIdentifier("app.update.current")
      }
    case .developmentBuild:
      Label("Version check unavailable", systemImage: "wrench.and.screwdriver")
        .foregroundStyle(.secondary)
        .help("This development build has no verifiable app version.")
    case .disabled:
      Label("Updates disabled for this build", systemImage: "arrow.down.circle")
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
