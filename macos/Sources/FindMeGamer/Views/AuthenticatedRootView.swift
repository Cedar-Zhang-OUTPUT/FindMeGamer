import FindMeGamerCore
import SwiftUI

private struct WorkspaceWritesEnabledKey: EnvironmentKey {
  static let defaultValue = true
}

extension EnvironmentValues {
  var workspaceWritesEnabled: Bool {
    get { self[WorkspaceWritesEnabledKey.self] }
    set { self[WorkspaceWritesEnabledKey.self] = newValue }
  }
}

struct AuthenticatedRootView: View {
  let session: AppSession
  @Bindable var navigation: WorkspaceNavigationState

  @Environment(\.scenePhase) private var scenePhase
  @SceneStorage("sidebar-selection") private var storedSelection = AppDestination.library.rawValue
  @State private var coordinator: ClientCoordinator?
  @State private var composerRequest: OutreachComposerRequest?

  init(session: AppSession, navigation: WorkspaceNavigationState) {
    self.session = session
    self.navigation = navigation
    if let service = session.service {
      let bundle = Bundle.main
      _coordinator = State(
        initialValue: ClientCoordinator(
          api: service,
          apiBaseURL: bundle.object(forInfoDictionaryKey: "FMGAPIBaseURL") as? String ?? "",
          appVersion: bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
            ?? "",
          workspaceIsOnline: session.state == .authenticated,
          disconnect: { await session.disconnectThisMac() }))
    } else {
      _coordinator = State(initialValue: nil)
    }
  }

  var body: some View {
    Group {
      if let coordinator {
        workspace(coordinator)
      } else {
        ContentUnavailableView(
          "Workspace unavailable",
          systemImage: "wifi.exclamationmark",
          description: Text("Reconnect to the workspace and try again."))
      }
    }
  }

  private func workspace(_ coordinator: ClientCoordinator) -> some View {
    NavigationSplitView(
      sidebar: {
        SidebarView(selection: sidebarSelection)
      },
      detail: {
        VStack(spacing: 0) {
          if session.workspaceSession?.workspaceName == "Find Me Gamer Demo" {
            Label("Local Demo Data · No real email will be sent", systemImage: "testtube.2")
              .font(.callout.weight(.medium))
              .foregroundStyle(.blue)
              .padding(10)
              .frame(maxWidth: .infinity, alignment: .leading)
              .background(Color.blue.opacity(0.08))
          } else if session.state == .offline {
            OfflineBanner(retry: retry)
          } else if session.state == .checking {
            HStack(spacing: 8) {
              ProgressView()
                .controlSize(.small)
              Text("Checking workspace access…")
                .font(.callout)
            }
            .foregroundStyle(.secondary)
            .padding(10)
            .frame(maxWidth: .infinity, alignment: .leading)
          }

          if selectedDestination == .match, let error = coordinator.outreach.resendError {
            Label(error, systemImage: "exclamationmark.triangle")
              .foregroundStyle(.red)
              .textSelection(.enabled)
              .padding(10)
              .frame(maxWidth: .infinity, alignment: .leading)
              .background(Color.red.opacity(0.08))
          }

          selectedDetail(coordinator)
        }
      }
    )
    .environment(\.workspaceWritesEnabled, availability.writesEnabled)
    .onAppear { storedSelection = selectedDestination.rawValue }
    .task { await coordinator.run() }
    .onChange(of: session.state) { _, state in
      guard state == .authenticated || state == .offline else { return }
      Task {
        await coordinator.workspaceConnectionChanged(
          isOnline: state == .authenticated,
          visible: selectedDestination)
      }
    }
    .onChange(of: scenePhase) { _, phase in
      guard phase == .active else { return }
      Task { await coordinator.sceneBecameActive(visible: selectedDestination) }
    }
    .sheet(isPresented: profilePresentation(coordinator)) {
      profileSheet(coordinator)
        .environment(\.workspaceWritesEnabled, availability.writesEnabled)
    }
    .sheet(
      item: $composerRequest,
      onDismiss: { composerRequest = nil },
      content: { request in
        OutreachComposerSheet(
          model: coordinator.composer,
          matchID: request.matchID,
          creatorIDs: request.creatorIDs,
          onAccepted: { batch in
            Task { await coordinator.sendBatchAccepted(batch) }
          }
        )
        .environment(\.workspaceWritesEnabled, availability.writesEnabled)
      })
  }

  private var sidebarSelection: Binding<AppDestination?> {
    Binding(
      get: { selectedDestination },
      set: { storedSelection = ($0 ?? .library).rawValue })
  }

  private var selectedDestination: AppDestination {
    AppDestination.restoring(rawValue: storedSelection)
  }

  private var availability: WorkspaceAvailability {
    WorkspaceAvailability(state: session.state)
  }

  @ViewBuilder
  private func selectedDetail(_ coordinator: ClientCoordinator) -> some View {
    switch selectedDestination {
    case .library:
      NavigationStack(path: $navigation.libraryPath) {
        LibraryView(
          model: coordinator.library,
          analyzeModel: coordinator.analyze,
          onOpenProfile: { type, id in
            Task { await coordinator.openProfile(type: type, id: id) }
          })
      }
    case .match:
      NavigationStack(path: $navigation.matchPath) {
        MatchView(
          model: coordinator.match,
          onOpenProfile: { type, id in
            Task { await coordinator.openProfile(type: type, id: id) }
          },
          onComposeOutreach: { matchID, creatorIDs in
            composerRequest = OutreachComposerRequest(
              matchID: matchID,
              creatorIDs: creatorIDs)
          },
          onResendDelivery: { deliveryID in
            Task { await coordinator.resendDelivery(id: deliveryID) }
          })
      }
    case .outreach:
      NavigationStack(path: $navigation.outreachPath) {
        OutreachManagementView(model: coordinator.outreach) {
          EmailSettingsView(model: coordinator.settings)
        }
      }
    case .settings:
      NavigationStack(path: $navigation.settingsPath) {
        SettingsView(model: coordinator.settings)
      }
    }
  }

  private func profilePresentation(_ coordinator: ClientCoordinator) -> Binding<Bool> {
    Binding(
      get: { coordinator.isProfilePresentationActive },
      set: { presented in
        if !presented { coordinator.dismissProfile() }
      })
  }

  @ViewBuilder
  private func profileSheet(_ coordinator: ClientCoordinator) -> some View {
    if coordinator.isLoadingProfile {
      ProgressView("Loading Profile…")
        .frame(minWidth: 420, minHeight: 260)
    } else if let profile = coordinator.presentedProfile {
      ProfileSheet(
        profile: profile,
        onFavorite: { type, id, favorite in
          try await coordinator.setProfileFavorite(type: type, id: id, favorite: favorite)
        },
        onReanalyze: { type, id, key in
          try await coordinator.reanalyzeProfile(
            type: type,
            id: id,
            callerIdempotencyKey: key)
        },
        onSaveManual: { id, email, notes in
          try await coordinator.updateCreatorManual(id: id, email: email, notes: notes)
        })
    } else {
      VStack(spacing: 14) {
        ContentUnavailableView(
          "Could not load Profile",
          systemImage: "exclamationmark.triangle",
          description: Text(coordinator.profileLoadError ?? "The Profile is unavailable."))
        HStack {
          Button("Close") { coordinator.dismissProfile() }
          Button("Try Again") {
            Task { await coordinator.retryProfileOpen() }
          }
          .buttonStyle(.borderedProminent)
        }
      }
      .padding(24)
      .frame(minWidth: 420, minHeight: 280)
    }
  }

  private func retry() {
    Task { await session.retryAccess(key: "") }
  }
}

private struct OutreachComposerRequest: Identifiable {
  let id = UUID()
  let matchID: UUID
  let creatorIDs: [UUID]
}
