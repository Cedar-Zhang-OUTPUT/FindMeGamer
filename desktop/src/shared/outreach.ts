import type { Result } from './bridge';
import type { WorkDetail } from './creators';
import type { JsonObject } from './library';
import type { EvaluationResult } from './match';

/** Strict v2 Activity outreach DTOs; backend field names remain snake_case. */
export interface PreparationContact {
  id: string;
  email: string;
  purpose: string | null;
  source_url: string | null;
  source_type: string;
  source_fields: JsonObject;
  manual_overrides: JsonObject;
  validation_state: string;
  identity_revision: number;
  updated_at: string;
  status: 'eligible' | 'inactive' | 'invalid' | 'historical';
}

export interface PreparationWork extends WorkDetail {
  relation: 'current_game' | 'reference_game' | 'related_content';
  evidence_status: 'recorded_evidence' | 'metadata_only';
}

export interface SelectionIdentity {
  platform: 'youtube' | 'x' | 'twitch' | 'instagram';
  account_id: string;
  revision: number;
}

export interface Preparation {
  id: string;
  activity_id: string;
  creator_id: string;
  candidate_id: string;
  active: boolean;
  revision: number;
  identity: SelectionIdentity;
  identity_changed: boolean;
  game_changed: boolean;
  name: string | null;
  public_name: string | null;
  public_name_confirmed: boolean;
  name_confirmed_at: string | null;
  contact_options: PreparationContact[];
  selected_contact: PreparationContact | null;
  contact_status: 'not_selected' | 'eligible' | 'changed' | 'inactive' | 'invalid' | 'historical' | 'missing';
  works: PreparationWork[];
  missing_work_ids: string[];
  evaluation: EvaluationResult | null;
  evaluation_run_id: string | null;
  missing_fields: string[];
  context_token: string;
  freeze_ready: boolean;
  send_ready: false;
  sender_watched: false;
  pending_send_requirements: string[];
}

export interface SelectionCreate { candidate_id: string }
export interface SelectionRevision { expected_revision: number }
export interface SelectionCancelChoice extends SelectionRevision { selection_id: string }
export interface SelectionBulkChange {
  add_candidate_ids?: string[];
  cancel_selections?: SelectionCancelChoice[];
}
export interface SelectionBulkResult {
  added_selection_ids: string[];
  cancelled_selection_ids: string[];
}
export interface SelectionUpdate extends SelectionRevision {
  context_token: string;
  contact_id?: string | null;
  evaluation_run_id?: string | null;
  work_ids?: string[];
  confirm_public_name?: boolean;
}
export interface RecipientChoice extends SelectionRevision {
  selection_id: string;
  context_token: string;
}
export interface RecipientBatchCreate {
  request_id: string;
  recipients: RecipientChoice[];
}
export interface FrozenRecipient {
  id: string;
  selection_id: string;
  snapshot: Preparation;
  preparation: Preparation;
  source_changed: boolean;
  current_missing_fields: string[];
}
export interface RecipientBatchSummary {
  id: string;
  activity_id: string;
  request_id: string;
  status: 'frozen';
  send_ready: false;
  recipient_count: number;
  send_ready_count: 0;
  needs_repair_count: number;
  created_at: string;
}
export interface RecipientBatchDetail extends RecipientBatchSummary {
  source_snapshot: JsonObject;
  recipients: FrozenRecipient[];
}
export interface SelectionPage { items: Preparation[]; total: number; limit: number; offset: number }
export interface RecipientBatchPage { items: RecipientBatchSummary[]; total: number; limit: number; offset: number }

export interface OutreachAPI {
  selections(input: { activityId: string; includeCancelled?: boolean; offset?: number; limit?: number }): Promise<Result<SelectionPage>>;
  selection(input: { activityId: string; id: string }): Promise<Result<Preparation>>;
  add(input: { activityId: string; data: SelectionCreate; idempotencyKey: string }): Promise<Result<Preparation>>;
  bulk(input: { activityId: string; data: SelectionBulkChange; idempotencyKey: string }): Promise<Result<SelectionBulkResult>>;
  update(input: { activityId: string; id: string; data: SelectionUpdate; idempotencyKey: string }): Promise<Result<Preparation>>;
  cancel(input: { activityId: string; id: string; data: SelectionRevision; idempotencyKey: string }): Promise<Result<Preparation>>;
  batches(input: { activityId: string; offset?: number; limit?: number }): Promise<Result<RecipientBatchPage>>;
  batch(input: { activityId: string; id: string }): Promise<Result<RecipientBatchDetail>>;
  freeze(input: { activityId: string; data: RecipientBatchCreate; idempotencyKey: string }): Promise<Result<RecipientBatchDetail>>;
}
