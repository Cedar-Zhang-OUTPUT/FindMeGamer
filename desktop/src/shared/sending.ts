import type { Result } from './bridge';
import type { JsonObject } from './library';
import type { SlotValues } from './drafts';
export interface Exclusion { draft_id: string; reason: string }
export interface QualificationRequest { excluded: Exclusion[] }
export interface FinalSendRequest extends QualificationRequest { request_id: string; qualification_token: string }
export interface SendingIdentity { address: string | null; name: string | null; reply_to: string | null }
export interface QualifiedMember {
  draft_id: string; recipient_snapshot_id: string; status: 'eligible' | 'needs_repair' | 'excluded'; missing_fields: string[];
  exclusion_reason: string | null; recipient_email: string | null; subject: string; html: string | null; text: string | null;
  values: SlotValues | null; slot_sources: JsonObject; template_version_id: string; fixed_hash: string; revision: number;
  context_token: string; sender_facts: JsonObject; identity: JsonObject; blocking_delivery_id: string | null;
}
export interface Qualification {
  composition_id: string; activity_id: string; qualification_token: string; sending_account_token: string;
  total_count: number; eligible_count: number; repair_count: number; excluded_count: number;
  sender: SendingIdentity; members: QualifiedMember[]; send_ready: boolean;
}
export interface DeliverySnapshot extends QualifiedMember { status: 'eligible'; sender: SendingIdentity; sending_account_token: string }
export interface Delivery {
  id: string; send_batch_id: string; draft_id: string; recipient_snapshot_id: string; snapshot: DeliverySnapshot;
  state: 'queued' | 'sending' | 'sent' | 'failed' | 'unknown'; attempt: number; retryable: boolean; error_code: string | null;
  sending_at: string | null; sent_at: string | null; failed_at: string | null;
  resolution: Record<string, never> | { outcome: 'sent' | 'not_sent'; source_note: string; at: string; attempt: number };
}
export interface SendBatch { id: string; activity_id: string; composition_id: string; created_at: string; qualification: Qualification; deliveries: Delivery[] }
export interface SendBatchPage { items: SendBatch[]; total: number; limit: number; offset: number }
export interface DeliveryRetry { expected_attempt: number }
export interface DeliveryResolution extends DeliveryRetry { outcome: 'sent' | 'not_sent'; source_note: string }
export interface SendingAPI {
  qualify(input: { compositionId: string; data: QualificationRequest }): Promise<Result<Qualification>>;
  send(input: { compositionId: string; data: FinalSendRequest; idempotencyKey: string }): Promise<Result<SendBatch>>;
  batches(input: { activityId: string; offset?: number; limit?: number }): Promise<Result<SendBatchPage>>;
  batch(id: string): Promise<Result<SendBatch>>;
  retry(input: { id: string; data: DeliveryRetry }): Promise<Result<Delivery>>;
  resolve(input: { id: string; data: DeliveryResolution }): Promise<Result<Delivery>>;
}
