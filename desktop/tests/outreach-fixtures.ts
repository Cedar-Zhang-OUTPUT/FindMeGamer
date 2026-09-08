import type { Preparation, RecipientBatchDetail, RecipientBatchSummary } from '../src/shared/outreach';
import { contactFixture, workFixture } from './creator-fixtures';
import { ACTIVITY_ID, CANDIDATE_ID, evaluationResultFixture, MATCH_TIME } from './match-fixtures';

export const SELECTION_ID = '34567890-3456-4456-8456-34567890abcd';
export const SECOND_SELECTION_ID = '45678901-4567-4567-8567-45678901abcd';
export const RECIPIENT_ID = '56789012-5678-4678-8678-56789012abcd';
export const RECIPIENT_BATCH_ID = '67890123-6789-4789-8789-67890123abcd';
export const REQUEST_ID = '78901234-7890-4890-8890-78901234abcd';
export const CONTEXT_TOKEN = 'a'.repeat(64);
export const OUTREACH_KEY = 'outreach-test-key';

export function preparationFixture(overrides: Partial<Preparation> = {}): Preparation {
  const baseContact = contactFixture();
  const contact = {
    id: baseContact.id,
    email: baseContact.email,
    purpose: baseContact.purpose,
    source_url: baseContact.source_url,
    source_type: baseContact.source_type,
    source_fields: baseContact.source_fields,
    manual_overrides: baseContact.manual_overrides,
    validation_state: baseContact.validation_state,
    identity_revision: baseContact.identity_revision,
    updated_at: baseContact.updated_at,
    status: 'eligible' as const,
  };
  return {
    id: SELECTION_ID,
    activity_id: ACTIVITY_ID,
    creator_id: evaluationResultFixture().creator_id,
    candidate_id: CANDIDATE_ID,
    active: true,
    revision: 3,
    identity: { platform: 'youtube', account_id: 'UCfixture', revision: 1 },
    identity_changed: false,
    game_changed: false,
    name: 'Creator fixture',
    public_name: 'Creator',
    public_name_confirmed: true,
    name_confirmed_at: MATCH_TIME,
    contact_options: [contact],
    selected_contact: contact,
    contact_status: 'eligible',
    works: [{ ...workFixture(), relation: 'current_game', evidence_status: 'recorded_evidence' }],
    missing_work_ids: [],
    evaluation: evaluationResultFixture(),
    evaluation_run_id: '12345678-1234-4234-8234-123456789abc',
    missing_fields: [],
    context_token: CONTEXT_TOKEN,
    freeze_ready: true,
    send_ready: false,
    sender_watched: false,
    pending_send_requirements: ['template_and_content_validation'],
    ...overrides,
  };
}

export function recipientBatchFixture(overrides: Partial<RecipientBatchDetail> = {}): RecipientBatchDetail {
  const current = preparationFixture();
  const snapshot = preparationFixture({ contact_options: [] });
  return {
    id: RECIPIENT_BATCH_ID,
    activity_id: ACTIVITY_ID,
    request_id: REQUEST_ID,
    status: 'frozen',
    send_ready: false,
    recipient_count: 1,
    send_ready_count: 0,
    needs_repair_count: 1,
    created_at: MATCH_TIME,
    source_snapshot: { game: { id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb' } },
    recipients: [{ id: RECIPIENT_ID, selection_id: SELECTION_ID, snapshot, preparation: current,
      source_changed: false, current_missing_fields: [] }],
    ...overrides,
  };
}

export function recipientBatchSummaryFixture(): RecipientBatchSummary {
  const { source_snapshot: _source, recipients: _recipients, ...summary } = recipientBatchFixture();
  return summary;
}
