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

enum WorkspaceInspectorPolicy {
  static func isPresented(requested: Bool, destination: AppDestination) -> Bool {
    requested && destination == .library
  }
}

struct AuthenticatedRootView: View {
  let session: AppSession
  @Bindable var navigation: WorkspaceNavigationState

  @Environment(\.scenePhase) private var scenePhase
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @SceneStorage("sidebar-selection") private var storedSelection = AppDestination.discover.rawValue
  @State private var coordinator: ClientCoordinator?
  @State private var composerRequest: OutreachComposerRequest?
  @State private var destinationDirection = WorkspaceMotionDirection.stationary
  @State private var analyzePhase = AnalyzeWorkspacePhase.request
  @State private var latestAcceptedBatch: SendBatch?

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
        GeometryReader { viewport in
          VStack(spacing: 0) {
            if session.workspaceSession?.workspaceName == "Find Me Gamer Demo" {
              HStack(spacing: WorkspaceDesign.spaceS) {
                Label("Demo · No real email sent", systemImage: "testtube.2")
                  .font(.caption.weight(.medium))
                  .foregroundStyle(.secondary)
                Spacer()
              }
              .padding(.horizontal, WorkspaceDesign.spaceM)
              .padding(.vertical, 6)
              .background(.bar)
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

            ZStack {
              selectedDetail(coordinator)
                .id(selectedDestination)
                // Never keep two NavigationStacks alive in the split-view detail
                // during an exit transition. Animate the incoming page content only.
                .transition(.identity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .clipped()
          }
          .frame(width: viewport.size.width, height: viewport.size.height, alignment: .topLeading)
        }
        .workspaceCanvas()
        .inspector(isPresented: analyzeInspectorPresentation(coordinator)) {
          AnalyzeRequestInspector(
            model: coordinator.analyze,
            phase: $analyzePhase,
            writesEnabled: availability.writesEnabled,
            onOpenProfile: { type, id in
              Task { await coordinator.openProfile(type: type, id: id) }
            }
          )
          .inspectorColumnWidth(min: 320, ideal: 380, max: 480)
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
          recipients: request.recipients,
          onAccepted: { batch in
            latestAcceptedBatch = batch
            Task { await coordinator.sendBatchAccepted(batch) }
          }
        )
        .environment(\.workspaceWritesEnabled, availability.writesEnabled)
      })
  }

  private func analyzeInspectorPresentation(_ coordinator: ClientCoordinator) -> Binding<Bool> {
    Binding(
      get: {
        WorkspaceInspectorPolicy.isPresented(
          requested: coordinator.analyze.inspectorPresented,
          destination: selectedDestination)
      },
      set: { coordinator.analyze.inspectorPresented = $0 })
  }

  private var sidebarSelection: Binding<AppDestination?> {
    Binding(
      get: { selectedDestination },
      set: { proposedDestination in
        let destination = proposedDestination ?? .discover
        guard destination != selectedDestination else { return }

        if destination != .library {
          coordinator?.analyze.inspectorPresented = false
        }

        destinationDirection = WorkspaceMotionPolicy.direction(
          from: selectedDestination,
          to: destination,
          ordered: AppDestination.allCases)
        withAnimation(
          WorkspaceMotionPolicy.animation(for: .destination, reduceMotion: reduceMotion)
        ) {
          storedSelection = destination.rawValue
        }
      })
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
    case .discover:
      NavigationStack(path: $navigation.discoverPath) {
        DiscoverView(
          model: coordinator.discover,
          onOpenMatch: { id in
            navigation.requestedMatchID = id
            sidebarSelection.wrappedValue = .match
          },
          onAnalysisHistory: {
            analyzePhase = .activity
            coordinator.analyze.inspectorPresented = true
            sidebarSelection.wrappedValue = .library
          }
        )
        .modifier(WorkspacePageEntrance(direction: destinationDirection))
      }
    case .library:
      NavigationStack(path: $navigation.libraryPath) {
        LibraryView(
          model: coordinator.library,
          analyzeModel: coordinator.analyze,
          onOpenAnalyze: { phase in
            analyzePhase = phase
            coordinator.analyze.inspectorPresented = true
          },
          onOpenProfile: { type, id in
            Task { await coordinator.openProfile(type: type, id: id) }
          }
        )
        .modifier(WorkspacePageEntrance(direction: destinationDirection))
      }
    case .match:
      NavigationStack(path: $navigation.matchPath) {
        MatchView(
          model: coordinator.match,
          onOpenProfile: { type, id in
            Task { await coordinator.openProfile(type: type, id: id) }
          },
          onComposeOutreach: { matchID, recipients in
            composerRequest = OutreachComposerRequest(
              matchID: matchID,
              recipients: recipients)
          },
          onResendDelivery: { deliveryID in
            Task { await coordinator.resendDelivery(id: deliveryID) }
          },
          acceptedBatch: latestAcceptedBatch,
          onViewCampaign: { campaignID in
            navigation.openCampaign(id: campaignID)
            sidebarSelection.wrappedValue = .outreach
          },
          onAddProfile: { type in
            if coordinator.analyze.isSubmitting {
              analyzePhase = .activity
            } else {
              coordinator.analyze.targetType = type
              coordinator.library.selectType(type)
              analyzePhase = .request
            }
            // Reuse the existing request draft and jobs; navigating here never
            // clears a source URL or starts an analysis without submission.
            sidebarSelection.wrappedValue = .library
            coordinator.analyze.inspectorPresented = true
          },
          onLoaded: {
            if let id = navigation.requestedMatchID {
              navigation.requestedMatchID = nil
              navigation.matchPath = NavigationPath([MatchRoute.result(id)])
            }
          }
        )
        .modifier(WorkspacePageEntrance(direction: destinationDirection))
      }
    case .outreach:
      NavigationStack {
        OutreachManagementView(
          model: coordinator.outreach,
          onStartMatch: { sidebarSelection.wrappedValue = .match },
          onOpenCampaign: { campaignID in
            navigation.openCampaign(id: campaignID)
          }
        ) {
          EmailSettingsView(model: coordinator.settings)
        }
        .modifier(WorkspacePageEntrance(direction: destinationDirection))
        // Outreach has one detail level. Bind that concrete destination directly:
        // no type-erased path registration or self-cancelling navigation task.
        .navigationDestination(item: $navigation.outreachCampaign) { destination in
          CampaignDetailView(model: coordinator.outreach, campaignID: destination.id)
        }
      }
    case .settings:
      NavigationStack(path: $navigation.settingsPath) {
        SettingsView(model: coordinator.settings)
          .modifier(WorkspacePageEntrance(direction: destinationDirection))
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
        },
        onReadEdit: { try await coordinator.profileEdit(type: $0, id: $1) },
        onSaveEdit: { try await coordinator.saveProfileEdit(type: $0, id: $1, patch: $2) },
        onRefreshEdit: { try await coordinator.refreshEditedProfile(type: $0, id: $1) })
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
  let recipients: [OutreachRecipientContext]
}
