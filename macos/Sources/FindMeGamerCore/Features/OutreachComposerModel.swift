import Foundation
import Observation

@MainActor
@Observable
public final class OutreachComposerModel {
  private struct SendAttempt: Equatable {
    let draft: SendBatchDraft
    let key: String
  }

  public private(set) var matchID: UUID?
  public private(set) var creatorIDs: [UUID] = []
  public private(set) var templates: [OutreachTemplate] = []
  public private(set) var selectedTemplate: OutreachTemplate?
  public private(set) var subjectDraft = ""
  public private(set) var bodyMarkdownDraft = ""
  public private(set) var previews: [RecipientPreview] = []
  public private(set) var selectedRecipientID: UUID?

  public private(set) var isLoading = false
  public private(set) var isPreviewing = false
  public private(set) var isSending = false
  public private(set) var loadError: String?
  public private(set) var previewError: String?
  public private(set) var sendError: String?
  public private(set) var acceptedBatch: SendBatch?

  public var selectedPreview: RecipientPreview? {
    previews.first { $0.creatorID == selectedRecipientID }
  }

  public var canRefreshPreview: Bool {
    acceptedBatch == nil && !isLoading && !isPreviewing && !isSending && currentDraft != nil
  }

  public var canConfirmSend: Bool {
    acceptedBatch == nil && !isLoading && !isPreviewing && !isSending
      && previewedDraft != nil && previewedDraft == currentDraft
  }

  @ObservationIgnored private let api: any APIService
  @ObservationIgnored private let idempotencyKey: @Sendable () -> String
  @ObservationIgnored private var contextGeneration: UInt64 = 0
  @ObservationIgnored private var compositionGeneration: UInt64 = 0
  @ObservationIgnored private var previewGeneration: UInt64 = 0
  @ObservationIgnored private var sendGeneration: UInt64 = 0
  @ObservationIgnored private var previewedDraft: SendBatchDraft?
  @ObservationIgnored private var sendAttempt: SendAttempt?

  public init(
    api: any APIService,
    idempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString }
  ) {
    self.api = api
    self.idempotencyKey = idempotencyKey
  }

  public func load(matchID: UUID, creatorIDs: [UUID]) async {
    guard !isSending else { return }
    contextGeneration &+= 1
    compositionGeneration &+= 1
    previewGeneration &+= 1
    sendGeneration &+= 1
    let context = contextGeneration
    let orderedCreatorIDs = Self.uniqueCreatorIDs(creatorIDs)

    self.matchID = matchID
    self.creatorIDs = orderedCreatorIDs
    templates = []
    selectedTemplate = nil
    subjectDraft = ""
    bodyMarkdownDraft = ""
    previews = []
    selectedRecipientID = nil
    previewedDraft = nil
    sendAttempt = nil
    acceptedBatch = nil
    isLoading = false
    isPreviewing = false
    isSending = false
    loadError = nil
    previewError = nil
    sendError = nil

    guard (1...30).contains(orderedCreatorIDs.count) else {
      loadError = "Select at least one Creator."
      return
    }

    isLoading = true
    do {
      let loadedTemplates = try await api.listTemplates()
      guard contextGeneration == context else { return }
      isLoading = false
      guard !loadedTemplates.isEmpty else {
        loadError = "No Outreach Template is available."
        return
      }

      templates = loadedTemplates
      let template = loadedTemplates.first(where: \.isDefault) ?? loadedTemplates[0]
      selectedTemplate = template
      subjectDraft = template.subjectTemplate
      bodyMarkdownDraft = template.bodyMarkdown
      await requestPreview(context: context, composition: compositionGeneration)
    } catch {
      guard contextGeneration == context else { return }
      isLoading = false
      loadError = Self.message(from: error, fallback: "Could not load Outreach Templates.")
    }
  }

  public func selectTemplate(id: UUID) async {
    guard !isSending, selectedTemplate?.id != id,
      let template = templates.first(where: { $0.id == id })
    else {
      return
    }

    invalidateComposition(clearAttempt: true)
    selectedTemplate = template
    subjectDraft = template.subjectTemplate
    bodyMarkdownDraft = template.bodyMarkdown
    await requestPreview(context: contextGeneration, composition: compositionGeneration)
  }

  public func updateOverride(subject: String, bodyMarkdown: String) {
    guard !isSending, subjectDraft != subject || bodyMarkdownDraft != bodyMarkdown else { return }
    invalidateComposition(clearAttempt: true)
    subjectDraft = subject
    bodyMarkdownDraft = bodyMarkdown
  }

  public func selectRecipient(id: UUID) {
    guard previews.contains(where: { $0.creatorID == id }) else { return }
    selectedRecipientID = id
  }

  public func refreshPreview() async {
    guard !isSending else { return }
    await requestPreview(context: contextGeneration, composition: compositionGeneration)
  }

  public func confirmSend() async {
    guard canConfirmSend, let draft = previewedDraft else { return }
    isSending = true
    sendError = nil
    sendGeneration &+= 1
    let generation = sendGeneration
    let composition = compositionGeneration
    let attempt: SendAttempt
    if let retained = sendAttempt, retained.draft == draft {
      attempt = retained
    } else {
      attempt = SendAttempt(draft: draft, key: nextIdempotencyKey())
      sendAttempt = attempt
    }
    defer {
      if sendGeneration == generation {
        isSending = false
      }
    }

    do {
      let batch = try await api.createSendBatch(draft, idempotencyKey: attempt.key)
      guard sendGeneration == generation, compositionGeneration == composition,
        currentDraft == draft, previewedDraft == draft
      else { return }
      guard batch.matchTaskID == draft.matchTaskID,
        batch.requestedCreatorIDs == draft.creatorIDs
      else {
        sendError = "Could not send Outreach."
        return
      }
      acceptedBatch = batch
      sendAttempt = nil
    } catch {
      guard sendGeneration == generation, compositionGeneration == composition,
        currentDraft == draft, previewedDraft == draft
      else { return }
      sendError = Self.message(from: error, fallback: "Could not send Outreach.")
    }
  }

  private var currentDraft: SendBatchDraft? {
    guard let matchID, !creatorIDs.isEmpty, let selectedTemplate,
      !subjectDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      !bodyMarkdownDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    else { return nil }
    return SendBatchDraft(
      matchTaskID: matchID, creatorIDs: creatorIDs, templateID: selectedTemplate.id,
      subjectOverride: subjectDraft == selectedTemplate.subjectTemplate ? nil : subjectDraft,
      bodyMarkdownOverride: bodyMarkdownDraft == selectedTemplate.bodyMarkdown
        ? nil : bodyMarkdownDraft)
  }

  private func requestPreview(context: UInt64, composition: UInt64) async {
    guard acceptedBatch == nil, contextGeneration == context,
      compositionGeneration == composition, let draft = currentDraft
    else { return }

    previewGeneration &+= 1
    let generation = previewGeneration
    isPreviewing = true
    previewError = nil
    previews = []
    previewedDraft = nil
    defer {
      if contextGeneration == context && compositionGeneration == composition
        && previewGeneration == generation
      {
        isPreviewing = false
      }
    }

    do {
      let response = try await api.previewSendBatch(draft)
      guard contextGeneration == context, compositionGeneration == composition,
        previewGeneration == generation, currentDraft == draft
      else { return }
      guard Self.hasExactRecipients(response, expected: creatorIDs) else {
        previewError = "Could not preview Outreach."
        return
      }

      let retainedSelection = selectedRecipientID
      previews = response
      previewedDraft = draft
      if let retainedSelection,
        response.contains(where: { $0.creatorID == retainedSelection })
      {
        selectedRecipientID = retainedSelection
      } else {
        selectedRecipientID = response.first?.creatorID
      }
    } catch {
      guard contextGeneration == context, compositionGeneration == composition,
        previewGeneration == generation, currentDraft == draft
      else { return }
      previewError = Self.message(from: error, fallback: "Could not preview Outreach.")
    }
  }

  private func invalidateComposition(clearAttempt: Bool) {
    compositionGeneration &+= 1
    previewGeneration &+= 1
    sendGeneration &+= 1
    previews = []
    previewedDraft = nil
    isPreviewing = false
    isSending = false
    previewError = nil
    sendError = nil
    if clearAttempt {
      sendAttempt = nil
    }
  }

  private func nextIdempotencyKey() -> String {
    let candidate = idempotencyKey()
    return UUID(uuidString: candidate) == nil ? UUID().uuidString : candidate
  }

  private static func uniqueCreatorIDs(_ ids: [UUID]) -> [UUID] {
    var seen = Set<UUID>()
    return ids.filter { seen.insert($0).inserted }
  }

  private static func hasExactRecipients(
    _ previews: [RecipientPreview], expected: [UUID]
  ) -> Bool {
    let responseIDs = previews.map(\.creatorID)
    return responseIDs.count == expected.count && Set(responseIDs).count == responseIDs.count
      && Set(responseIDs) == Set(expected)
  }

  private static func message(from error: Error, fallback: String) -> String {
    (error as? APIError)?.description ?? fallback
  }
}
