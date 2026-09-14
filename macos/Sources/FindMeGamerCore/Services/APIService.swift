import Foundation

public protocol APIService: Sendable {
  func validateSession() async throws -> WorkspaceSession
  func listJobs(changedAfter: String?, status: JobStatus?) async throws -> JobChangePage
  func createAnalysisJob(_ request: AnalysisRequest, idempotencyKey: String) async throws
    -> AnalysisSubmission
  func retryAnalysisJob(id: UUID, idempotencyKey: String) async throws -> AnalysisJob
  func listProfiles(
    type: ProfileType, query: String, onlyCollection: Bool, cursor: String?, limit: Int
  ) async throws -> ProfileCardPage
  func profile(type: ProfileType, id: UUID) async throws -> Profile
  func profileEdit(type: ProfileType, id: UUID) async throws -> ProfileEditDocument
  func saveProfileEdit(type: ProfileType, id: UUID, patch: ProfileEditPatch) async throws -> ProfileEditDocument
  func setFavorite(type: ProfileType, id: UUID, favorite: Bool) async throws -> ProfileCard
  func updateCreatorManual(id: UUID, email: String?, notes: String) async throws
    -> CreatorProfile
  func createMatch(gameID: UUID, idempotencyKey: String) async throws -> MatchTask
  func listMatches(cursor: String?) async throws -> MatchTaskPage
  func match(id: UUID) async throws -> MatchResult
  func retryMatch(id: UUID, idempotencyKey: String) async throws -> MatchTask
  func listCampaigns(cursor: String?) async throws -> CampaignPage
  func campaign(id: UUID) async throws -> OutreachCampaign
  func listTemplates() async throws -> [OutreachTemplate]
  func saveTemplate(_ draft: TemplateDraft) async throws -> OutreachTemplate
  func duplicateTemplate(id: UUID) async throws -> OutreachTemplate
  func setDefaultTemplate(id: UUID) async throws -> OutreachTemplate
  func deleteTemplate(id: UUID) async throws
  func previewTemplate(_ draft: TemplateDraft) async throws -> RenderedEmail
  func previewSendBatch(_ request: SendBatchDraft) async throws -> [RecipientPreview]
  func createSendBatch(_ request: SendBatchDraft, idempotencyKey: String) async throws
    -> SendBatch
  func resendDelivery(id: UUID, idempotencyKey: String) async throws -> Delivery
  func smtpSettings() async throws -> SMTPSettingsStatus
  func saveSMTPSettings(_ draft: SMTPSettingsDraft) async throws -> SMTPSettingsStatus
  func testSMTPConnection(_ draft: SMTPSettingsDraft?) async throws -> ConnectionTestResult
  func sendSMTPTest(to email: String) async throws -> ConnectionTestResult
  func sharedSettings() async throws -> SharedSettings
  func saveReanalysis(_ draft: ReanalysisDraft) async throws -> SharedSettings
  func connection(_ service: ConnectionService) async throws -> ConnectionStatus
  func replaceConnection(_ service: ConnectionService, secret: String) async throws
    -> ConnectionStatus
  func testConnection(_ service: ConnectionService) async throws -> ConnectionTestResult
}
