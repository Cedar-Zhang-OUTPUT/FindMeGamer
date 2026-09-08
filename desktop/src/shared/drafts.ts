import type { Result } from './bridge';
import type { JsonObject } from './library';

export interface SlotValues { firstName: string; channelName: string; reference: string; observation: string }
export interface TemplateSource { kind: 'canonical' | 'user_saved'; document_id: string | null; revision: number | null; steam_app_id: string | null; raw_hash: string | null }
export interface TemplateContent { name: string; subject: string; fixed_fragments: string[]; fixed_hash: string; source_metadata: TemplateSource }
export interface TemplateVersion extends TemplateContent { id: string; game_id: string; created_at: string }
export interface BuiltinTemplate extends TemplateContent { key: 'liminal-revision-69'; requires_explicit_registration: true }
export interface TemplateCatalog { items: TemplateVersion[]; builtin: BuiltinTemplate }
export interface TemplateVersionCreate { game_id: string; request_id: string; name: string; subject: string; fixed_fragments: string[] }
export interface CompositionCreate { request_id: string; recipient_batch_id: string; template_version_id: string }
export interface DraftRevision { expected_revision: number; context_token: string }
export interface DraftEdit extends DraftRevision { values: SlotValues }
export interface FactMember extends DraftRevision { draft_id: string }
export interface SenderFacts { members: FactMember[]; following: boolean; enjoyed: boolean; liked: boolean }
export interface DraftView {
  id: string; composition_id: string; recipient_snapshot_id: string; selection_id: string; input_order: number; revision: number;
  context_token: string; source_changed: boolean; status: 'pending' | 'running' | 'succeeded' | 'failed' | 'needs_repair'; error_code: string | null;
  input: JsonObject; values: SlotValues | null; missing_fields: string[]; slot_sources: JsonObject;
  rendered: { subject: string; html: string; text: string; fixed_hash: string } | null;
  sender_facts_valid: boolean; sender_facts: JsonObject; send_ready: false;
}
export interface CompositionView { id: string; activity_id: string; recipient_batch_id: string; template_version_id: string; created_at: string; recipient_count: number; drafts: DraftView[]; send_ready: false }
export interface CompositionPage { items: CompositionView[]; total: number; limit: number; offset: number }
export interface DraftsAPI {
  templates(input: { gameId: string }): Promise<Result<TemplateCatalog>>;
  template(id: string): Promise<Result<TemplateVersion>>;
  registerCanonical(input: { gameId: string; idempotencyKey: string }): Promise<Result<TemplateVersion>>;
  createTemplate(input: { data: TemplateVersionCreate; idempotencyKey: string }): Promise<Result<TemplateVersion>>;
  compositions(input: { activityId: string; offset?: number; limit?: number }): Promise<Result<CompositionPage>>;
  composition(id: string): Promise<Result<CompositionView>>;
  createComposition(input: { activityId: string; data: CompositionCreate; idempotencyKey: string }): Promise<Result<CompositionView>>;
  edit(input: { id: string; data: DraftEdit }): Promise<Result<DraftView>>;
  refresh(input: { id: string; data: DraftRevision }): Promise<Result<DraftView>>;
  retry(input: { id: string; data: DraftRevision }): Promise<Result<DraftView>>;
  senderFacts(input: { compositionId: string; data: SenderFacts }): Promise<Result<CompositionView>>;
}
