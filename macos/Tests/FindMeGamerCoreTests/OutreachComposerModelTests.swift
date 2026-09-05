import Foundation
import Testing

@testable import FindMeGamerCore

@Suite(.serialized)
struct OutreachComposerModelTests {
  @MainActor
  @Test func loadValidatesContextAndChoosesDefaultBeforeExactAutomaticPreview() async {
    let first = template(id: id(1), name: "First", subject: "First subject", isDefault: false)
    let preferred = template(
      id: id(2), name: "Preferred", subject: "Hello {{creator}}", body: "Body {{game}}",
      isDefault: true)
    let creators = [id(11), id(12)]
    let response = [
      preview(creatorID: creators[1], name: "Second"), preview(creatorID: creators[0]),
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([first, preferred])], previewOutcomes: [.value(response)])
    let model = OutreachComposerModel(api: api)

    await model.load(matchID: id(10), recipients: testRecipients([]))
    #expect(model.loadError == "Select at least one Creator.")
    await model.load(matchID: id(10), recipients: testRecipients((1...31).map(id)))
    #expect(model.loadError == "Select at least one Creator.")
    #expect(await api.templateCallCount == 0)

    await model.load(
      matchID: id(10),
      recipients: testRecipients([creators[0], creators[1], creators[0]]))

    #expect(model.matchID == id(10))
    #expect(model.creatorIDs == creators)
    #expect(model.templates == [first, preferred])
    #expect(model.selectedTemplate == preferred)
    #expect(model.subjectDraft == "Hello {{creator}}")
    #expect(model.bodyMarkdownDraft == "Body {{game}}")
    #expect(model.previews == response)
    #expect(model.selectedRecipientID == creators[1])
    #expect(model.selectedPreview == response[0])
    #expect(model.canConfirmSend)
    #expect(await api.templateCallCount == 1)
    #expect(
      await api.previewCalls == [
        SendBatchDraft(
          matchTaskID: id(10), creatorIDs: creators, templateID: preferred.id,
          subjectOverride: nil, bodyMarkdownOverride: nil)
      ])
    #expect(await api.sendCalls.isEmpty)
  }

  @MainActor
  @Test func loadFailuresAndLateContextCannotReplaceCurrentContext() async {
    let aGate = ComposerGate<[OutreachTemplate]>()
    let templateB = template(id: id(21), name: "B", subject: "B subject")
    let previewB = [preview(creatorID: id(22), name: "B Creator")]
    let api = OutreachAPI(
      templateOutcomes: [
        .gated(aGate), .value([templateB]), .value([]),
        .failure(APIError(code: "offline", message: "Templates unavailable.", retryable: true)),
      ],
      previewOutcomes: [.value(previewB)])
    let model = OutreachComposerModel(api: api)

    let loadA = Task {
      await model.load(matchID: id(20), recipients: testRecipients([id(23)]))
    }
    #expect(await aGate.waitUntilEntered())
    await model.load(matchID: id(24), recipients: testRecipients([id(22)]))
    aGate.resume(.success([template(id: id(25), name: "A", subject: "A subject")]))
    await loadA.value

    #expect(model.matchID == id(24))
    #expect(model.creatorIDs == [id(22)])
    #expect(model.selectedTemplate == templateB)
    #expect(model.previews == previewB)

    await model.load(matchID: id(26), recipients: testRecipients([id(27)]))
    #expect(model.loadError == "No Outreach Template is available.")
    #expect(model.selectedTemplate == nil)
    #expect(model.previews.isEmpty)

    await model.load(matchID: id(28), recipients: testRecipients([id(29)]))
    #expect(model.loadError == "Templates unavailable.")
    #expect(!model.canRefreshPreview)
    #expect(!model.canConfirmSend)
  }

  @MainActor
  @Test func failedInitialTemplateLoadCanRetryWithoutReopeningComposer() async {
    let creator = id(129)
    let loadedTemplate = template(id: id(130), name: "Recovered Template")
    let rendered = [preview(creatorID: creator)]
    let api = OutreachAPI(
      templateOutcomes: [
        .failure(APIError(code: "offline", message: "Templates unavailable.", retryable: true)),
        .value([loadedTemplate]),
      ],
      previewOutcomes: [.value(rendered)])
    let model = OutreachComposerModel(api: api)

    await model.load(matchID: id(128), recipients: testRecipients([creator]))

    #expect(model.loadError == "Templates unavailable.")
    #expect(model.canRetryLoad)
    #expect(model.templates.isEmpty)

    await model.retryLoad()

    #expect(model.loadError == nil)
    #expect(!model.canRetryLoad)
    #expect(model.templates == [loadedTemplate])
    #expect(model.previews == rendered)
    #expect(await api.templateCallCount == 2)
  }

  @MainActor
  @Test func editsInvalidatePreviewAndEncodeOnlyExactSendOverrides() async {
    let shared = template(
      id: id(31), name: "Shared", subject: "Original subject", body: "Original body")
    let creator = id(32)
    let initial = [preview(creatorID: creator, subject: "Rendered original")]
    let edited = [
      preview(
        creatorID: creator, subject: "Rendered edited", markdown: "Rendered body",
        html: "<p>Rendered body</p>")
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([shared])], previewOutcomes: [.value(initial), .value(edited)])
    let model = OutreachComposerModel(api: api)
    await model.load(matchID: id(30), recipients: testRecipients([creator]))

    model.updateOverride(subject: "Exact one-off subject", bodyMarkdown: shared.bodyMarkdown)
    #expect(model.selectedTemplate == shared)
    #expect(model.previews.isEmpty)
    #expect(!model.canConfirmSend)
    #expect(model.canRefreshPreview)

    await model.refreshPreview()
    #expect(model.previews == edited)
    #expect(model.canConfirmSend)
    #expect(
      await api.previewCalls.last
        == SendBatchDraft(
          matchTaskID: id(30), creatorIDs: [creator], templateID: shared.id,
          subjectOverride: "Exact one-off subject", bodyMarkdownOverride: nil))
    #expect(await api.saveTemplateCallCount == 0)

    model.updateOverride(subject: "   ", bodyMarkdown: "Still body")
    #expect(!model.canRefreshPreview)
    #expect(!model.canConfirmSend)
  }

  @MainActor
  @Test func templateSwitchFencesHeldPreviewAndSameSelectionPreservesEdits() async {
    let first = template(id: id(41), name: "First", subject: "First subject", body: "First body")
    let second = template(
      id: id(42), name: "Second", subject: "Second subject", body: "Second body")
    let creator = id(43)
    let oldGate = ComposerGate<[RecipientPreview]>()
    let current = [preview(creatorID: creator, subject: "Second rendered")]
    let api = OutreachAPI(
      templateOutcomes: [.value([first, second])],
      previewOutcomes: [.gated(oldGate), .value(current)])
    let model = OutreachComposerModel(api: api)

    let load = Task {
      await model.load(matchID: id(40), recipients: testRecipients([creator]))
    }
    #expect(await oldGate.waitUntilEntered())
    await model.selectTemplate(id: second.id)
    #expect(model.selectedTemplate == second)
    #expect(model.subjectDraft == "Second subject")
    #expect(model.bodyMarkdownDraft == "Second body")
    #expect(model.previews == current)

    oldGate.resume(.success([preview(creatorID: creator, subject: "Stale first")]))
    await load.value
    #expect(model.previews == current)

    model.updateOverride(subject: "Keep this edit", bodyMarkdown: "Keep this body")
    let callsBefore = await api.previewCalls.count
    await model.selectTemplate(id: second.id)
    #expect(model.subjectDraft == "Keep this edit")
    #expect(model.bodyMarkdownDraft == "Keep this body")
    #expect(await api.previewCalls.count == callsBefore)
  }

  @MainActor
  @Test func editedBodyPreviewPreservesRecipientSelectionAndUsesOnlyBodyOverride() async {
    let creators = [id(44), id(45)]
    let shared = template(
      id: id(46), name: "Shared", subject: "Shared subject", body: "Shared body")
    let initial = [preview(creatorID: creators[0]), preview(creatorID: creators[1])]
    let refreshed = [
      preview(creatorID: creators[0], subject: "First refreshed"),
      preview(creatorID: creators[1], subject: "Second refreshed"),
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([shared])],
      previewOutcomes: [.value(initial), .value(refreshed)])
    let model = OutreachComposerModel(api: api)
    await model.load(matchID: id(47), recipients: testRecipients(creators))
    model.selectRecipient(id: creators[1])

    model.updateOverride(subject: shared.subjectTemplate, bodyMarkdown: "Exact one-off body")
    await model.refreshPreview()

    #expect(model.selectedRecipientID == creators[1])
    #expect(model.selectedPreview?.subject == "Second refreshed")
    #expect(
      await api.previewCalls.last
        == SendBatchDraft(
          matchTaskID: id(47), creatorIDs: creators, templateID: shared.id,
          subjectOverride: nil, bodyMarkdownOverride: "Exact one-off body"))
  }

  @MainActor
  @Test func previewFencesLateFailureAndValidatesRecipientIdentityWithoutReordering() async {
    let creators = [id(51), id(52)]
    let initial = [
      preview(creatorID: creators[1], name: "Second"), preview(creatorID: creators[0]),
    ]
    let heldFailure = ComposerGate<[RecipientPreview]>()
    let newer = [
      preview(
        creatorID: creators[0], name: "First", subject: "Exact A", markdown: "Markdown A",
        html: "<p>A</p>"),
      preview(
        creatorID: creators[1], name: "Second", subject: "Exact B", markdown: "Markdown B",
        html: "<p>B</p>"),
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([template(id: id(53), name: "Only")])],
      previewOutcomes: [
        .value(initial), .gated(heldFailure), .value(newer),
        .value([preview(creatorID: creators[0]), preview(creatorID: creators[0])]),
      ])
    let model = OutreachComposerModel(api: api)
    await model.load(matchID: id(50), recipients: testRecipients(creators))
    model.selectRecipient(id: creators[0])

    let olderRefresh = Task { await model.refreshPreview() }
    #expect(await heldFailure.waitUntilEntered())
    await model.refreshPreview()
    #expect(model.previews == newer)
    #expect(model.selectedRecipientID == creators[0])
    #expect(model.selectedPreview?.subject == "Exact A")
    #expect(model.selectedPreview?.markdown == "Markdown A")
    #expect(model.selectedPreview?.html == "<p>A</p>")

    heldFailure.resume(
      .failure(APIError(code: "stale", message: "Old preview failed.", retryable: true)))
    await olderRefresh.value
    #expect(model.previews == newer)
    #expect(model.previewError == nil)
    #expect(model.canConfirmSend)

    await model.refreshPreview()
    #expect(model.previews.isEmpty)
    #expect(model.previewError == "Could not preview Outreach.")
    #expect(!model.canConfirmSend)
  }

  @MainActor
  @Test func confirmIsExplicitSingleFlightAndAcceptsMatchingIdentityOnce() async {
    let creator = id(61)
    let draftPreview = [preview(creatorID: creator)]
    let gate = ComposerGate<SendBatch>()
    let api = OutreachAPI(
      templateOutcomes: [.value([template(id: id(62), name: "Only")])],
      previewOutcomes: [.value(draftPreview)], sendOutcomes: [.gated(gate)])
    let keys = ComposerKeySequence([
      "00000000-0000-4000-8000-000000000063"
    ])
    let model = OutreachComposerModel(api: api, idempotencyKey: keys.provider)
    await model.load(matchID: id(60), recipients: testRecipients([creator]))

    #expect(await api.sendCalls.isEmpty)
    #expect(model.canConfirmSend)
    let sending = Task { await model.confirmSend() }
    #expect(await gate.waitUntilEntered())
    #expect(model.isSending)
    await model.confirmSend()
    #expect(await api.sendCalls.count == 1)

    let accepted = batch(id: id(64), matchID: id(60), creatorIDs: [creator])
    gate.resume(.success(accepted))
    await sending.value
    #expect(model.acceptedBatch == accepted)
    #expect(!model.canConfirmSend)
    #expect(await api.sendCalls.first?.draft == api.previewCalls.first)
    #expect(await api.sendCalls.first?.key == keys.values[0])
    await model.confirmSend()
    #expect(await api.sendCalls.count == 1)
  }

  @MainActor
  @Test func failedConfirmationReusesKeyButEditedDraftUsesNewKeyAndRejectsMismatch() async {
    let creator = id(71)
    let template = template(id: id(72), name: "Only", subject: "Initial")
    let api = OutreachAPI(
      templateOutcomes: [.value([template])],
      previewOutcomes: [
        .value([preview(creatorID: creator)]),
        .value([preview(creatorID: creator, subject: "Edited rendered")]),
      ],
      sendOutcomes: [
        .failure(APIError(code: "lost", message: "Response was lost.", retryable: true)),
        .value(batch(id: id(73), matchID: id(999), creatorIDs: [creator])),
        .value(batch(id: id(74), matchID: id(70), creatorIDs: [id(998)])),
      ])
    let keys = ComposerKeySequence([
      "00000000-0000-4000-8000-000000000075",
      "00000000-0000-4000-8000-000000000076",
    ])
    let model = OutreachComposerModel(api: api, idempotencyKey: keys.provider)
    await model.load(matchID: id(70), recipients: testRecipients([creator]))

    await model.confirmSend()
    #expect(model.sendError == "Response was lost.")
    #expect(model.previews.count == 1)
    #expect(model.canConfirmSend)
    await model.confirmSend()
    #expect(model.sendError == "Could not send Outreach.")
    #expect(model.acceptedBatch == nil)
    #expect(await api.sendCalls.map(\.key) == [keys.values[0], keys.values[0]])

    model.updateOverride(subject: "Edited exact", bodyMarkdown: template.bodyMarkdown)
    await model.refreshPreview()
    await model.confirmSend()
    #expect(model.acceptedBatch == nil)
    #expect(model.sendError == "Could not send Outreach.")
    #expect(await api.sendCalls.map(\.key) == [keys.values[0], keys.values[0], keys.values[1]])
    #expect(await api.sendCalls.last?.draft.subjectOverride == "Edited exact")
  }

  @MainActor
  @Test func inFlightSendKeepsEveryCompositionMutationLockedUntilAcceptance() async {
    let creator = id(81)
    let first = template(id: id(82), name: "First", subject: "Locked subject")
    let second = template(id: id(83), name: "Second", subject: "Other subject")
    let gate = ComposerGate<SendBatch>()
    let api = OutreachAPI(
      templateOutcomes: [.value([first, second]), .value([second])],
      previewOutcomes: [
        .value([preview(creatorID: creator)]),
        .value([preview(creatorID: creator, subject: "Changed")]),
        .value([preview(creatorID: id(84), subject: "Other context")]),
        .value([preview(creatorID: id(84), subject: "Other refresh")]),
      ],
      sendOutcomes: [
        .gated(gate), .value(batch(id: id(85), matchID: id(86), creatorIDs: [id(84)])),
      ])
    let model = OutreachComposerModel(
      api: api,
      idempotencyKey: ComposerKeySequence([
        "00000000-0000-4000-8000-000000000087",
        "00000000-0000-4000-8000-000000000088",
      ]).provider)
    await model.load(matchID: id(80), recipients: testRecipients([creator]))

    let sending = Task { await model.confirmSend() }
    #expect(await gate.waitUntilEntered())
    model.updateOverride(subject: "Changed", bodyMarkdown: first.bodyMarkdown)
    await model.selectTemplate(id: second.id)
    await model.load(matchID: id(86), recipients: testRecipients([id(84)]))
    await model.refreshPreview()
    await model.confirmSend()

    #expect(model.isSending)
    #expect(model.matchID == id(80))
    #expect(model.creatorIDs == [creator])
    #expect(model.selectedTemplate == first)
    #expect(model.subjectDraft == "Locked subject")
    #expect(await api.templateCallCount == 1)
    #expect(await api.previewCalls.count == 1)
    #expect(await api.sendCalls.count == 1)

    let accepted = batch(id: id(89), matchID: id(80), creatorIDs: [creator])
    gate.resume(.success(accepted))
    await sending.value
    #expect(model.acceptedBatch == accepted)
    #expect(!model.isSending)
  }

  @MainActor
  @Test func multipleEmailsRequireOneExplicitActiveSelectionBeforePreviewing() async {
    let creator = id(91)
    let first = recipientContact(
      email: "business@example.com", purpose: "Sponsorships", source: "channel_about")
    let second = recipientContact(
      email: "press@example.com", purpose: "Press", source: "public_web_research")
    let api = OutreachAPI(
      templateOutcomes: [.value([template(id: id(92), name: "Only")])],
      previewOutcomes: [
        .value([preview(creatorID: creator, recipientEmail: second.email)])
      ])
    let model = OutreachComposerModel(api: api)

    await model.load(
      matchID: id(90),
      recipients: [recipient(id: creator, name: "Multi Creator", contacts: [first, second])])

    #expect(model.creatorIDs == [creator])
    #expect(model.recipientContexts.first?.contacts == [first, second])
    #expect(model.selectedEmail(for: creator) == nil)
    #expect(model.recipientIDsRequiringSelection == [creator])
    #expect(!model.canRefreshPreview)
    #expect(!model.canConfirmSend)
    #expect(await api.previewCalls.isEmpty)

    await model.selectRecipientEmail("not-active@example.com", creatorID: creator)
    #expect(model.selectedEmail(for: creator) == nil)
    #expect(await api.previewCalls.isEmpty)

    await model.selectRecipientEmail(second.email, creatorID: creator)

    let expectedSelection = OutreachRecipientSelection(creatorID: creator, email: second.email)
    #expect(model.selectedEmail(for: creator) == second.email)
    #expect(model.recipientIDsRequiringSelection.isEmpty)
    #expect(await api.previewCalls.count == 1)
    #expect(await api.previewCalls.first?.recipientSelections == [expectedSelection])
    #expect(model.canConfirmSend)
  }

  @MainActor
  @Test func recipientSelectionRefreshesPreviewAndSendUsesExactlyOneAddressPerCreator() async {
    let creator = id(94)
    let contacts = [
      recipientContact(email: "first@example.com", source: "channel_about"),
      recipientContact(email: "second@example.com", source: "public_web_research"),
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([template(id: id(95), name: "Only")])],
      previewOutcomes: [
        .value([
          preview(
            creatorID: creator, recipientEmail: contacts[0].email,
            subject: "First selection")
        ]),
        .value([
          preview(
            creatorID: creator, recipientEmail: contacts[1].email,
            subject: "Second selection")
        ]),
      ],
      sendOutcomes: [.value(batch(id: id(96), matchID: id(93), creatorIDs: [creator]))])
    let model = OutreachComposerModel(
      api: api,
      idempotencyKey: { "00000000-0000-4000-8000-000000000097" })
    await model.load(
      matchID: id(93),
      recipients: [recipient(id: creator, name: "Creator", contacts: contacts)])

    await model.selectRecipientEmail(contacts[0].email, creatorID: creator)
    #expect(model.selectedPreview?.subject == "First selection")
    await model.selectRecipientEmail(contacts[1].email, creatorID: creator)
    #expect(model.selectedPreview?.subject == "Second selection")
    #expect(await api.previewCalls.count == 2)
    #expect(
      await api.previewCalls.last?.recipientSelections == [
        OutreachRecipientSelection(creatorID: creator, email: contacts[1].email)
      ])

    await model.confirmSend()
    #expect(await api.sendCalls.count == 1)
    #expect(await api.sendCalls.first?.draft == api.previewCalls.last)
    #expect(model.acceptedBatch?.id == id(96))
  }

  @MainActor
  @Test func oneEmailNeedsNoSelectionAndMissingEmailStopsCompositionLocally() async {
    let singleCreator = id(101)
    let missingCreator = id(102)
    let singleAPI = OutreachAPI(
      templateOutcomes: [.value([template(id: id(103), name: "Only")])],
      previewOutcomes: [
        .value([preview(creatorID: singleCreator, recipientEmail: "only@example.com")])
      ])
    let singleModel = OutreachComposerModel(api: singleAPI)
    await singleModel.load(
      matchID: id(100),
      recipients: [
        recipient(
          id: singleCreator, name: "Single",
          contacts: [recipientContact(email: "only@example.com", source: "manual")])
      ])

    #expect(singleModel.recipientIDsRequiringSelection.isEmpty)
    #expect(singleModel.selectedEmail(for: singleCreator) == nil)
    #expect(await singleAPI.previewCalls.first?.recipientSelections == [])
    #expect(singleModel.canConfirmSend)

    let missingAPI = OutreachAPI()
    let missingModel = OutreachComposerModel(api: missingAPI)
    await missingModel.load(
      matchID: id(100),
      recipients: [recipient(id: missingCreator, name: "Missing", contacts: [])])

    #expect(missingModel.loadError == "Every Creator must have an available email address.")
    #expect(await missingAPI.templateCallCount == 0)
    #expect(await missingAPI.previewCalls.isEmpty)
  }

  @MainActor
  @Test func serverPreviewMustConfirmTheExactSelectedOrOnlyActiveEmail() async {
    let creator = id(111)
    let contacts = [
      recipientContact(email: "first@example.com", source: "channel_about"),
      recipientContact(email: "second@example.com", source: "public_web_research"),
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([template(id: id(112), name: "Only")])],
      previewOutcomes: [
        .value([preview(creatorID: creator, recipientEmail: contacts[0].email)])
      ])
    let model = OutreachComposerModel(api: api)
    await model.load(
      matchID: id(110),
      recipients: [recipient(id: creator, name: "Creator", contacts: contacts)])

    await model.selectRecipientEmail(contacts[1].email, creatorID: creator)

    #expect(model.previews.isEmpty)
    #expect(model.previewError == "Could not preview Outreach.")
    #expect(!model.canConfirmSend)
  }

  @MainActor
  @Test func multipleRecipientSelectionsSerializeInCreatorOrderRegardlessOfInteractionOrder()
    async
  {
    let firstCreator = id(121)
    let secondCreator = id(122)
    let firstContacts = [
      recipientContact(email: "first-primary@example.com", source: "channel_about"),
      recipientContact(email: "first-press@example.com", source: "public_web_research"),
    ]
    let secondContacts = [
      recipientContact(email: "second-primary@example.com", source: "channel_about"),
      recipientContact(email: "second-press@example.com", source: "public_web_research"),
    ]
    let api = OutreachAPI(
      templateOutcomes: [.value([template(id: id(123), name: "Only")])],
      previewOutcomes: [
        .value([
          preview(creatorID: firstCreator, recipientEmail: firstContacts[1].email),
          preview(creatorID: secondCreator, recipientEmail: secondContacts[0].email),
        ])
      ],
      sendOutcomes: [
        .value(
          batch(
            id: id(124), matchID: id(120), creatorIDs: [firstCreator, secondCreator]))
      ])
    let model = OutreachComposerModel(api: api)
    await model.load(
      matchID: id(120),
      recipients: [
        recipient(id: firstCreator, name: "First", contacts: firstContacts),
        recipient(id: secondCreator, name: "Second", contacts: secondContacts),
      ])

    await model.selectRecipientEmail(secondContacts[0].email, creatorID: secondCreator)
    #expect(await api.previewCalls.isEmpty)

    await model.selectRecipientEmail(firstContacts[1].email, creatorID: firstCreator)

    let expectedSelections = [
      OutreachRecipientSelection(creatorID: firstCreator, email: firstContacts[1].email),
      OutreachRecipientSelection(creatorID: secondCreator, email: secondContacts[0].email),
    ]
    #expect(await api.previewCalls.first?.recipientSelections == expectedSelections)
    #expect(model.canConfirmSend)

    await model.confirmSend()

    #expect(await api.sendCalls.first?.draft.recipientSelections == expectedSelections)
  }
}

private struct ComposerSendCall: Sendable, Equatable {
  let draft: SendBatchDraft
  let key: String
}

private enum ComposerOutcome<Value: Sendable>: Sendable {
  case value(Value)
  case failure(APIError)
  case gated(ComposerGate<Value>)
}

private final class ComposerGate<Value: Sendable>: @unchecked Sendable {
  private let lock = NSLock()
  private var continuation: CheckedContinuation<Result<Value, APIError>, Never>?
  private var entered = false

  func wait() async -> Result<Value, APIError> {
    await withCheckedContinuation { continuation in
      lock.withLock {
        entered = true
        self.continuation = continuation
      }
    }
  }

  func waitUntilEntered() async -> Bool {
    for _ in 0..<1_000 {
      if lock.withLock({ entered }) { return true }
      await Task.yield()
    }
    return lock.withLock { entered }
  }

  func resume(_ result: Result<Value, APIError>) {
    let pending = lock.withLock {
      let pending = continuation
      continuation = nil
      return pending
    }
    pending?.resume(returning: result)
  }
}

private final class ComposerKeySequence: @unchecked Sendable {
  let values: [String]
  private let lock = NSLock()
  private var index = 0

  init(_ values: [String]) { self.values = values }

  var provider: @Sendable () -> String {
    { [self] in
      lock.withLock {
        defer { index += 1 }
        return values[index]
      }
    }
  }
}

private actor OutreachAPI: APIService {
  private var templateOutcomes: [ComposerOutcome<[OutreachTemplate]>]
  private var previewOutcomes: [ComposerOutcome<[RecipientPreview]>]
  private var sendOutcomes: [ComposerOutcome<SendBatch>]

  private(set) var templateCallCount = 0
  private(set) var previewCalls: [SendBatchDraft] = []
  private(set) var sendCalls: [ComposerSendCall] = []
  private(set) var saveTemplateCallCount = 0

  init(
    templateOutcomes: [ComposerOutcome<[OutreachTemplate]>] = [],
    previewOutcomes: [ComposerOutcome<[RecipientPreview]>] = [],
    sendOutcomes: [ComposerOutcome<SendBatch>] = []
  ) {
    self.templateOutcomes = templateOutcomes
    self.previewOutcomes = previewOutcomes
    self.sendOutcomes = sendOutcomes
  }

  func listTemplates() async throws -> [OutreachTemplate] {
    templateCallCount += 1
    return try await resolve(templateOutcomes.removeFirst())
  }

  func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate {
    saveTemplateCallCount += 1
    fatalError("OutreachComposerModel must not save shared Templates")
  }

  func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview] {
    previewCalls.append(request)
    return try await resolve(previewOutcomes.removeFirst())
  }

  func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  {
    sendCalls.append(ComposerSendCall(draft: request, key: idempotencyKey))
    return try await resolve(sendOutcomes.removeFirst())
  }

  private func resolve<Value: Sendable>(_ outcome: ComposerOutcome<Value>) async throws -> Value {
    switch outcome {
    case .value(let value): return value
    case .failure(let error): throw error
    case .gated(let gate): return try await gate.wait().get()
    }
  }
}

extension APIService {
  fileprivate func validateSession() async throws -> WorkspaceSession { fatalError("unused") }
  fileprivate func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage
  {
    fatalError("unused")
  }
  fileprivate func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String)
    async throws -> AnalysisSubmission
  { fatalError("unused") }
  fileprivate func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob {
    fatalError("unused")
  }
  fileprivate func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage { fatalError("unused") }
  fileprivate func profile(type: ProfileType, id: UUID) async throws -> Profile {
    fatalError("unused")
  }
  fileprivate func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws
    -> ProfileCard
  { fatalError("unused") }
  fileprivate func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  { fatalError("unused") }
  fileprivate func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func listMatches(cursor: String?) async throws -> MatchTaskPage {
    fatalError("unused")
  }
  fileprivate func match(id: UUID) async throws -> MatchResult { fatalError("unused") }
  fileprivate func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask {
    fatalError("unused")
  }
  fileprivate func listCampaigns(cursor: String?) async throws -> CampaignPage {
    fatalError("unused")
  }
  fileprivate func campaign(id: UUID) async throws -> OutreachCampaign { fatalError("unused") }
  fileprivate func duplicateTemplate(id: UUID) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate {
    fatalError("unused")
  }
  fileprivate func deleteTemplate(id: UUID) async throws { fatalError("unused") }
  fileprivate func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail {
    fatalError("unused")
  }
  fileprivate func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery {
    fatalError("unused")
  }
  fileprivate func smtpSettings() async throws -> SMTPSettingsStatus { fatalError("unused") }
  fileprivate func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus {
    fatalError("unused")
  }
  fileprivate func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws
    -> ConnectionTestResult
  { fatalError("unused") }
  fileprivate func sendSMTPTest(to email: String) async throws -> ConnectionTestResult {
    fatalError("unused")
  }
  fileprivate func sharedSettings() async throws -> SharedSettings { fatalError("unused") }
  fileprivate func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings {
    fatalError("unused")
  }
  fileprivate func connection(_ service: ConnectionService) async throws -> ConnectionStatus {
    fatalError("unused")
  }
  fileprivate func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  { fatalError("unused") }
  fileprivate func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult
  {
    fatalError("unused")
  }
}

private func id(_ suffix: Int) -> UUID {
  UUID(uuidString: String(format: "00000000-0000-4000-8000-%012d", suffix))!
}

private func template(
  id: UUID,
  name: String,
  subject: String = "Subject {{creator}}",
  body: String = "Hello {{creator}} about {{game}}",
  isDefault: Bool = false
) -> OutreachTemplate {
  OutreachTemplate(
    id: id, name: name, version: 3, subjectTemplate: subject, bodyMarkdown: body,
    acceptedLabel: "I'm interested", declinedLabel: "Not right now", isDefault: isDefault,
    createdAt: Date(timeIntervalSince1970: 1), updatedAt: Date(timeIntervalSince1970: 2))
}

private func preview(
  creatorID: UUID,
  name: String = "Creator",
  recipientEmail: String = "creator@example.com",
  subject: String = "Rendered subject",
  markdown: String = "Rendered markdown",
  html: String = "<p>Rendered markdown</p>"
) -> RecipientPreview {
  RecipientPreview(
    creatorID: creatorID, creatorName: name, recipientEmail: recipientEmail,
    subject: subject, markdown: markdown, html: html)
}

private func recipientContact(
  email: String,
  purpose: String? = nil,
  source: String,
  sourceURL: String? = nil,
  validationState: String = "valid"
) -> OutreachRecipientContact {
  OutreachRecipientContact(
    email: email, purpose: purpose, source: source, sourceURL: sourceURL,
    validationState: validationState)
}

private func recipient(
  id: UUID,
  name: String,
  contacts: [OutreachRecipientContact]
) -> OutreachRecipientContext {
  OutreachRecipientContext(creatorID: id, creatorName: name, contacts: contacts)
}

private func testRecipients(_ creatorIDs: [UUID]) -> [OutreachRecipientContext] {
  creatorIDs.map { creatorID in
    recipient(
      id: creatorID,
      name: "Creator",
      contacts: [recipientContact(email: "creator@example.com", source: "manual")])
  }
}

private func batch(id batchID: UUID, matchID: UUID?, creatorIDs: [UUID]) -> SendBatch {
  SendBatch(
    id: batchID, campaignID: id(900), matchTaskID: matchID, templateID: id(901),
    templateName: "Template", templateVersion: 3, requestedCreatorIDs: creatorIDs,
    requestedAt: Date(timeIntervalSince1970: 3), state: .queued, deliveries: [])
}
