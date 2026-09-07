import FindMeGamerCore
import Observation
import Testing
import os

@testable import FindMeGamer

@Suite struct SettingsPresentationTests {
  @MainActor
  @Test func booleanDisclosuresAndConfirmationsNotifyWhenOpenedAndClosed() {
    let fields: [ReferenceWritableKeyPath<SettingsPresentation, Bool>] = [
      \.isShowingConnectionDetails, \.isShowingActivity,
      \.isShowingSaveConfirmation, \.isShowingDisconnectConfirmation,
    ]
    for field in fields {
      let presentation = SettingsPresentation()
      let opened = observe(presentation, field)

      presentation[keyPath: field] = true

      #expect(opened.withLock { $0 })
      #expect(presentation[keyPath: field])

      // Observation callbacks are one-shot; closing must notify a new consumer too.
      let closed = observe(presentation, field)
      presentation[keyPath: field] = false

      #expect(closed.withLock { $0 })
      #expect(!presentation[keyPath: field])
    }
  }

  @MainActor
  @Test func connectionExpansionAndReplacementNotifyIndependentConsumers() {
    let presentation = SettingsPresentation()
    let expanded = observe(presentation, \.expandedConnection)
    let replacement = observe(presentation, \.replacementConfirmation)

    presentation.expandedConnection = .steam

    #expect(expanded.withLock { $0 })
    #expect(!replacement.withLock { $0 })
    #expect(presentation.replacementConfirmation == nil)

    let expansionUnchanged = observe(presentation, \.expandedConnection)
    presentation.replacementConfirmation = .youtube

    #expect(replacement.withLock { $0 })
    #expect(!expansionUnchanged.withLock { $0 })
    #expect(presentation.expandedConnection == .steam)
    #expect(presentation.replacementConfirmation == .youtube)

    let replacementDismissed = observe(presentation, \.replacementConfirmation)
    presentation.expandedConnection = nil

    #expect(expansionUnchanged.withLock { $0 })
    #expect(!replacementDismissed.withLock { $0 })
    #expect(presentation.replacementConfirmation == .youtube)

    presentation.replacementConfirmation = nil
    #expect(replacementDismissed.withLock { $0 })
    #expect(presentation.expandedConnection == nil)
    #expect(presentation.replacementConfirmation == nil)
  }

  @MainActor
  @Test func newPresentationDoesNotInheritAnotherFormsExpandedOrPendingState() {
    let previous = SettingsPresentation()
    previous.expandedConnection = .steam
    previous.replacementConfirmation = .youtube
    previous.isShowingConnectionDetails = true
    previous.isShowingActivity = true
    previous.isShowingSaveConfirmation = true
    previous.isShowingDisconnectConfirmation = true

    let fresh = SettingsPresentation()

    #expect(fresh.expandedConnection == nil)
    #expect(fresh.replacementConfirmation == nil)
    #expect(!fresh.isShowingConnectionDetails)
    #expect(!fresh.isShowingActivity)
    #expect(!fresh.isShowingSaveConfirmation)
    #expect(!fresh.isShowingDisconnectConfirmation)
    #expect(previous.expandedConnection == .steam)
    #expect(previous.replacementConfirmation == .youtube)
    #expect(previous.isShowingConnectionDetails)
    #expect(previous.isShowingActivity)
    #expect(previous.isShowingSaveConfirmation)
    #expect(previous.isShowingDisconnectConfirmation)
  }

  @MainActor
  private func observe<Value>(
    _ presentation: SettingsPresentation, _ field: KeyPath<SettingsPresentation, Value>
  ) -> OSAllocatedUnfairLock<Bool> {
    let changed = OSAllocatedUnfairLock(initialState: false)
    withObservationTracking {
      _ = presentation[keyPath: field]
    } onChange: {
      changed.withLock { $0 = true }
    }
    return changed
  }
}
