import Foundation
import Observation

public enum OutreachManagementTab: String, CaseIterable, Sendable, Equatable, Hashable {
  case campaigns
  case templates
  case emailSettings

  public var displayName: String {
    switch self {
    case .campaigns: "Campaigns"
    case .templates: "Templates"
    case .emailSettings: "Email Settings"
    }
  }
}

public enum TemplatePreviewState: Sendable, Equatable {
  case idle
  case saveFirst(String)
  case loading
  case available(RenderedEmail)
  case failed(String)
}

@MainActor
@Observable
public final class OutreachManagementModel {
  public static let allowedVariables = [
    "{{creator_name}}", "{{channel_name}}", "{{game_name}}", "{{steam_url}}",
    "{{game_summary}}", "{{match_reason}}", "{{sender_name}}",
  ]

  public var selectedTab: OutreachManagementTab = .campaigns

  public private(set) var campaigns: [CampaignSummary] = []
  public private(set) var selectedCampaignID: UUID?
  public private(set) var selectedCampaign: OutreachCampaign?
  public private(set) var isLoadingCampaigns = false
  public private(set) var isLoadingCampaignDetail = false
  public private(set) var campaignsError: String?
  public private(set) var campaignError: String?

  public private(set) var resendingDeliveryIDs: Set<UUID> = []
  public private(set) var lastResentDelivery: Delivery?
  public private(set) var resendMessage: String?
  public private(set) var resendError: String?

  public private(set) var templates: [OutreachTemplate] = []
  public private(set) var selectedTemplateID: UUID?
  public private(set) var templateDraft: TemplateDraft?
  public private(set) var previewState: TemplatePreviewState = .idle
  public private(set) var isLoadingTemplates = false
  public private(set) var isSavingTemplate = false
  public private(set) var isDuplicatingTemplate = false
  public private(set) var isSettingDefaultTemplate = false
  public private(set) var isDeletingTemplate = false
  public private(set) var templatesError: String?
  public private(set) var templateActionError: String?

  public var isTemplateActionInFlight: Bool {
    isSavingTemplate || isDuplicatingTemplate || isSettingDefaultTemplate || isDeletingTemplate
  }

  public var hasUnsavedTemplateChanges: Bool {
    guard let draft = templateDraft else { return false }
    guard let selectedTemplateID,
      draft.id == selectedTemplateID,
      let canonical = templates.first(where: { $0.id == selectedTemplateID })
    else {
      return true
    }
    return draft != Self.draft(from: canonical)
  }

  public var templateValidationMessages: [String] {
    guard let draft = templateDraft else { return [] }
    var messages: [String] = []
    if draft.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      messages.append("Template Name is required.")
    }
    if draft.subjectTemplate.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      messages.append("Subject is required.")
    }
    if draft.bodyMarkdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      messages.append("Markdown Body is required.")
    }
    if draft.acceptedLabel?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false {
      messages.append("Accepted CTA Label is required.")
    }
    if draft.declinedLabel?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false {
      messages.append("Declined CTA Label is required.")
    }
    return messages
  }

  public var canSaveTemplate: Bool {
    templateDraft != nil && templateValidationMessages.isEmpty && !isTemplateActionInFlight
  }

  @ObservationIgnored private let api: any APIService
  @ObservationIgnored private let clock: any AppClock
  @ObservationIgnored private let idempotencyKey: @Sendable () -> String
  @ObservationIgnored private var campaignGeneration: UInt64 = 0
  @ObservationIgnored private var templateMutationGeneration: UInt64 = 0
  @ObservationIgnored private var previewGeneration: UInt64 = 0
  @ObservationIgnored private var previewTask: Task<Void, Never>?
  @ObservationIgnored private var resendKeys: [UUID: String] = [:]
  @ObservationIgnored private var suppressedResendIDs: Set<UUID> = []

  public init(
    api: any APIService,
    clock: any AppClock = ContinuousAppClock(),
    idempotencyKey: @escaping @Sendable () -> String = { UUID().uuidString }
  ) {
    self.api = api
    self.clock = clock
    self.idempotencyKey = idempotencyKey
  }

  deinit {
    previewTask?.cancel()
  }

  public func loadCampaigns() async {
    guard !isLoadingCampaigns else { return }
    isLoadingCampaigns = true
    campaignsError = nil
    defer { isLoadingCampaigns = false }

    do {
      var cursor: String?
      var hasMore = true
      var loaded: [CampaignSummary] = []
      var seen = Set<UUID>()
      while hasMore {
        let page = try await api.listCampaigns(cursor: cursor)
        for campaign in page.items where seen.insert(campaign.id).inserted {
          loaded.append(campaign)
        }
        cursor = page.cursor
        hasMore = page.hasMore && cursor != nil
      }
      campaigns = loaded
    } catch {
      campaignsError = Self.message(from: error, fallback: "Could not load Campaigns.")
    }
  }

  public func openCampaign(id: UUID) async {
    let keepsCurrentDetail = selectedCampaignID == id
    selectedCampaignID = id
    if !keepsCurrentDetail { selectedCampaign = nil }
    campaignError = nil
    campaignGeneration &+= 1
    let generation = campaignGeneration
    isLoadingCampaignDetail = true

    do {
      let campaign = try await api.campaign(id: id)
      guard selectedCampaignID == id, campaignGeneration == generation else { return }
      guard campaign.id == id else {
        campaignError = "Could not load Campaign details."
        return
      }
      selectedCampaign = campaign
    } catch {
      guard selectedCampaignID == id, campaignGeneration == generation else { return }
      campaignError = Self.message(from: error, fallback: "Could not load Campaign details.")
    }

    if selectedCampaignID == id, campaignGeneration == generation {
      isLoadingCampaignDetail = false
    }
  }

  public func canAttemptResend(id: UUID) -> Bool {
    !resendingDeliveryIDs.contains(id) && !suppressedResendIDs.contains(id)
  }

  public func resendDelivery(id: UUID) async {
    guard canAttemptResend(id: id) else { return }
    resendingDeliveryIDs.insert(id)
    resendError = nil
    resendMessage = nil
    let key = resendKeys[id] ?? nextIdempotencyKey()
    resendKeys[id] = key
    defer { resendingDeliveryIDs.remove(id) }

    do {
      let delivery = try await api.resendDelivery(id: id, idempotencyKey: key)
      guard delivery.resendsDeliveryID == id else {
        resendError = "Could not verify the resent Delivery."
        return
      }
      resendKeys[id] = nil
      suppressedResendIDs.insert(id)
      lastResentDelivery = delivery
      resendMessage = "Resend accepted."

      if let selectedCampaignID {
        await openCampaign(id: selectedCampaignID)
      }
    } catch {
      resendError = Self.message(from: error, fallback: "Could not resend this Delivery.")
    }
  }

  public func loadTemplates() async {
    guard !isLoadingTemplates else { return }
    let draftAtRequest = templateDraft
    let selectionAtRequest = selectedTemplateID
    let wasDirty = hasUnsavedTemplateChanges
    let mutationGenerationAtRequest = templateMutationGeneration
    isLoadingTemplates = true
    templatesError = nil
    defer { isLoadingTemplates = false }

    do {
      let loaded = try await api.listTemplates()
      guard templateMutationGeneration == mutationGenerationAtRequest else { return }
      let shouldPreserveDraft =
        wasDirty || templateDraft != draftAtRequest || selectedTemplateID != selectionAtRequest
      templates = loaded
      if shouldPreserveDraft { return }
      if let selected = loaded.first(where: \.isDefault) ?? loaded.first {
        adopt(selected)
      } else {
        selectedTemplateID = nil
        templateDraft = nil
        schedulePreview()
      }
    } catch {
      templatesError = Self.message(from: error, fallback: "Could not load Templates.")
    }
  }

  public func selectTemplate(id: UUID) {
    guard !isTemplateActionInFlight, !hasUnsavedTemplateChanges,
      let selected = templates.first(where: { $0.id == id })
    else {
      return
    }
    adopt(selected)
    templateActionError = nil
  }

  public func beginCreatingTemplate() {
    guard !isTemplateActionInFlight, !hasUnsavedTemplateChanges else { return }
    selectedTemplateID = nil
    templateDraft = TemplateDraft(
      name: "", subjectTemplate: "", bodyMarkdown: "", acceptedLabel: "Yes, I'm in",
      declinedLabel: "No, I'm not interested")
    templateActionError = nil
    schedulePreview()
  }

  public func discardTemplateChanges() {
    guard !isTemplateActionInFlight else { return }
    templateActionError = nil
    if let selectedTemplateID,
      let canonical = templates.first(where: { $0.id == selectedTemplateID })
    {
      adopt(canonical)
    } else if let fallback = templates.first(where: \.isDefault) ?? templates.first {
      adopt(fallback)
    } else {
      selectedTemplateID = nil
      templateDraft = nil
      schedulePreview()
    }
  }

  public func editTemplateName(_ value: String) {
    updateDraft(name: value)
  }

  public func editTemplateSubject(_ value: String) {
    updateDraft(subject: value)
  }

  public func editTemplateBody(_ value: String) {
    updateDraft(body: value)
  }

  public func editAcceptedLabel(_ value: String) {
    updateDraft(acceptedLabel: value)
  }

  public func editDeclinedLabel(_ value: String) {
    updateDraft(declinedLabel: value)
  }

  public func insertVariable(_ variable: String) {
    guard Self.allowedVariables.contains(variable), let draft = templateDraft else { return }
    editTemplateBody(draft.bodyMarkdown + variable)
  }

  public func saveTemplate() async {
    guard canSaveTemplate, let submitted = templateDraft else { return }
    isSavingTemplate = true
    templateActionError = nil
    defer { isSavingTemplate = false }

    do {
      let canonical = try await api.saveTemplate(submitted)
      templateMutationGeneration &+= 1
      upsert(canonical, enforceDefault: canonical.isDefault)
      adopt(canonical)
    } catch {
      templateActionError = Self.message(from: error, fallback: "Could not save this Template.")
    }
  }

  public func duplicateSelectedTemplate() async {
    guard !isTemplateActionInFlight, !hasUnsavedTemplateChanges, let id = selectedTemplateID else {
      return
    }
    isDuplicatingTemplate = true
    templateActionError = nil
    defer { isDuplicatingTemplate = false }

    do {
      let canonical = try await api.duplicateTemplate(id: id)
      templateMutationGeneration &+= 1
      upsert(canonical, enforceDefault: canonical.isDefault)
      adopt(canonical)
    } catch {
      templateActionError = Self.message(
        from: error, fallback: "Could not duplicate this Template.")
    }
  }

  public func setSelectedTemplateDefault() async {
    guard !isTemplateActionInFlight, !hasUnsavedTemplateChanges, let id = selectedTemplateID else {
      return
    }
    isSettingDefaultTemplate = true
    templateActionError = nil
    defer { isSettingDefaultTemplate = false }

    do {
      let canonical = try await api.setDefaultTemplate(id: id)
      templateMutationGeneration &+= 1
      upsert(canonical, enforceDefault: true)
      adopt(canonical)
    } catch {
      templateActionError = Self.message(
        from: error, fallback: "Could not set this Template as default.")
    }
  }

  public func deleteSelectedTemplate() async {
    guard !isTemplateActionInFlight, !hasUnsavedTemplateChanges, let id = selectedTemplateID else {
      return
    }
    isDeletingTemplate = true
    templateActionError = nil
    defer { isDeletingTemplate = false }

    do {
      try await api.deleteTemplate(id: id)
      templateMutationGeneration &+= 1
      templates.removeAll { $0.id == id }
      if let next = templates.first(where: \.isDefault) ?? templates.first {
        adopt(next)
      } else {
        selectedTemplateID = nil
        templateDraft = nil
        schedulePreview()
      }
    } catch {
      templateActionError = Self.message(from: error, fallback: "Could not delete this Template.")
    }
  }

  private func updateDraft(
    name: String? = nil,
    subject: String? = nil,
    body: String? = nil,
    acceptedLabel: String? = nil,
    declinedLabel: String? = nil
  ) {
    guard !isTemplateActionInFlight, let draft = templateDraft else { return }
    templateDraft = TemplateDraft(
      id: draft.id, name: name ?? draft.name,
      subjectTemplate: subject ?? draft.subjectTemplate,
      bodyMarkdown: body ?? draft.bodyMarkdown,
      acceptedLabel: acceptedLabel ?? draft.acceptedLabel,
      declinedLabel: declinedLabel ?? draft.declinedLabel)
    templateActionError = nil
    schedulePreview()
  }

  private func adopt(_ template: OutreachTemplate) {
    selectedTemplateID = template.id
    templateDraft = Self.draft(from: template)
    schedulePreview()
  }

  private static func draft(from template: OutreachTemplate) -> TemplateDraft {
    TemplateDraft(
      id: template.id, name: template.name, subjectTemplate: template.subjectTemplate,
      bodyMarkdown: template.bodyMarkdown, acceptedLabel: template.acceptedLabel,
      declinedLabel: template.declinedLabel)
  }

  private func upsert(_ template: OutreachTemplate, enforceDefault: Bool) {
    if enforceDefault {
      templates = templates.map { Self.replacingDefault($0, with: $0.id == template.id) }
    }
    if let index = templates.firstIndex(where: { $0.id == template.id }) {
      templates[index] = template
    } else {
      templates.append(template)
    }
  }

  private func schedulePreview() {
    previewTask?.cancel()
    previewGeneration &+= 1
    let generation = previewGeneration
    guard let draft = templateDraft else {
      previewState = .idle
      return
    }
    guard draft.id != nil else {
      previewState = .saveFirst("Save the Template to preview it.")
      return
    }

    previewState = .loading
    let clock = self.clock
    let api = self.api
    previewTask = Task { @MainActor [weak self] in
      do {
        try await clock.sleep(for: .milliseconds(300))
      } catch {
        return
      }
      guard let self, self.previewGeneration == generation, self.templateDraft == draft else {
        return
      }
      do {
        let preview = try await api.previewTemplate(draft)
        guard self.previewGeneration == generation, self.templateDraft == draft else { return }
        self.previewState = .available(preview)
      } catch {
        guard self.previewGeneration == generation, self.templateDraft == draft else { return }
        self.previewState = .failed(
          Self.message(from: error, fallback: "Could not preview this Template."))
      }
    }
  }

  private func nextIdempotencyKey() -> String {
    let candidate = idempotencyKey()
    return UUID(uuidString: candidate) == nil ? UUID().uuidString : candidate
  }

  private static func replacingDefault(_ template: OutreachTemplate, with isDefault: Bool)
    -> OutreachTemplate
  {
    OutreachTemplate(
      id: template.id, name: template.name, version: template.version,
      subjectTemplate: template.subjectTemplate, bodyMarkdown: template.bodyMarkdown,
      acceptedLabel: template.acceptedLabel, declinedLabel: template.declinedLabel,
      isDefault: isDefault, createdAt: template.createdAt, updatedAt: template.updatedAt)
  }

  private static func message(from error: Error, fallback: String) -> String {
    (error as? APIError)?.description ?? fallback
  }
}
