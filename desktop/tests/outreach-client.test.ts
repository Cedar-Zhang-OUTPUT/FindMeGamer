import { describe, expect, it, vi } from 'vitest';
import { OutreachClient, decodePreparation, decodeRecipientBatch } from '../src/main/outreach-client';
import { ACTIVITY_ID, CANDIDATE_ID } from './match-fixtures';
import { CONTACT_ID, WORK_ID } from './creator-fixtures';
import { CONTEXT_TOKEN, OUTREACH_KEY, RECIPIENT_BATCH_ID, REQUEST_ID, SECOND_SELECTION_ID, SELECTION_ID,
  preparationFixture, recipientBatchFixture, recipientBatchSummaryFixture } from './outreach-fixtures';

const page = (items: unknown[]) => ({ items, total: items.length, limit: 50, offset: 0 });
const revision = { expected_revision: 3 };

describe('Outreach client contract', () => {
  it('emits exactly the nine Activity-scoped operations and exact query names', async () => {
    const request = vi.fn(async input => {
      const path = (input as { path: string }).path;
      if (path.endsWith('/selections/bulk')) return { added_selection_ids: [SELECTION_ID], cancelled_selection_ids: [] };
      if (path.endsWith('/recipient-batches') && (input as { method: string }).method === 'GET') return page([recipientBatchSummaryFixture()]);
      if (path.includes('/recipient-batches')) return recipientBatchFixture();
      if (path.endsWith('/selections') && (input as { method: string }).method === 'GET') return page([preparationFixture()]);
      return preparationFixture();
    });
    const client = new OutreachClient(request);
    await client.selections({ activityId: ACTIVITY_ID, includeCancelled: true, offset: 2, limit: 25 });
    await client.selection({ activityId: ACTIVITY_ID, id: SELECTION_ID });
    await client.add({ activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_ID }, idempotencyKey: OUTREACH_KEY });
    await client.bulk({ activityId: ACTIVITY_ID, data: { add_candidate_ids: [CANDIDATE_ID] }, idempotencyKey: OUTREACH_KEY });
    await client.update({ activityId: ACTIVITY_ID, id: SELECTION_ID, data: { ...revision, context_token: CONTEXT_TOKEN }, idempotencyKey: OUTREACH_KEY });
    await client.cancel({ activityId: ACTIVITY_ID, id: SELECTION_ID, data: revision, idempotencyKey: OUTREACH_KEY });
    await client.batches({ activityId: ACTIVITY_ID, offset: 1, limit: 20 });
    await client.batch({ activityId: ACTIVITY_ID, id: RECIPIENT_BATCH_ID });
    await client.freeze({ activityId: ACTIVITY_ID, data: { request_id: REQUEST_ID,
      recipients: [{ selection_id: SELECTION_ID, expected_revision: 3, context_token: CONTEXT_TOKEN }] }, idempotencyKey: OUTREACH_KEY });

    const base = `/api/v2/activities/${ACTIVITY_ID}`;
    expect(request.mock.calls.map(call => call[0])).toEqual([
      { method: 'GET', path: `${base}/selections`, query: { include_cancelled: 'true', offset: '2', limit: '25' } },
      { method: 'GET', path: `${base}/selections/${SELECTION_ID}` },
      { method: 'POST', path: `${base}/selections`, body: { candidate_id: CANDIDATE_ID }, idempotencyKey: OUTREACH_KEY },
      { method: 'POST', path: `${base}/selections/bulk`, body: { add_candidate_ids: [CANDIDATE_ID] }, idempotencyKey: OUTREACH_KEY },
      { method: 'POST', path: `${base}/selections/${SELECTION_ID}/update`, body: { expected_revision: 3, context_token: CONTEXT_TOKEN }, idempotencyKey: OUTREACH_KEY },
      { method: 'POST', path: `${base}/selections/${SELECTION_ID}/cancel`, body: revision, idempotencyKey: OUTREACH_KEY },
      { method: 'GET', path: `${base}/recipient-batches`, query: { offset: '1', limit: '20' } },
      { method: 'GET', path: `${base}/recipient-batches/${RECIPIENT_BATCH_ID}` },
      { method: 'POST', path: `${base}/recipient-batches`, body: { request_id: REQUEST_ID,
        recipients: [{ selection_id: SELECTION_ID, expected_revision: 3, context_token: CONTEXT_TOKEN }] }, idempotencyKey: OUTREACH_KEY },
    ]);
  });

  it('preserves omitted update fields, explicit null/false, and a frozen ordered batch body', async () => {
    const request = vi.fn(async input => (input as { path: string }).path.endsWith('/recipient-batches') ? recipientBatchFixture() : preparationFixture());
    const client = new OutreachClient(request);
    await client.update({ activityId: ACTIVITY_ID, id: SELECTION_ID,
      data: { ...revision, context_token: CONTEXT_TOKEN, contact_id: null, evaluation_run_id: null, work_ids: [], confirm_public_name: false }, idempotencyKey: OUTREACH_KEY });
    const data = { request_id: REQUEST_ID, recipients: [
      { selection_id: SELECTION_ID, expected_revision: 3, context_token: CONTEXT_TOKEN },
      { selection_id: SECOND_SELECTION_ID, expected_revision: 0, context_token: 'b'.repeat(64) },
    ] };
    const original = structuredClone(data);
    Object.freeze(data.recipients[0]); Object.freeze(data.recipients[1]); Object.freeze(data.recipients); Object.freeze(data);
    const response = recipientBatchFixture({ recipient_count: 2, needs_repair_count: 2, recipients: [
      ...recipientBatchFixture().recipients,
      { ...recipientBatchFixture().recipients[0], id: '89012345-8901-4901-8901-89012345abcd', selection_id: SECOND_SELECTION_ID,
        snapshot: preparationFixture({ id: SECOND_SELECTION_ID, revision: 0, context_token: 'b'.repeat(64), contact_options: [] }),
        preparation: preparationFixture({ id: SECOND_SELECTION_ID }) },
    ] });
    request.mockResolvedValueOnce(response);
    await client.freeze({ activityId: ACTIVITY_ID, data, idempotencyKey: OUTREACH_KEY });
    expect(request.mock.calls[0][0]).toMatchObject({ body: { expected_revision: 3, context_token: CONTEXT_TOKEN,
      contact_id: null, evaluation_run_id: null, work_ids: [], confirm_public_name: false } });
    expect(request.mock.calls[1][0]).toMatchObject({ body: original, idempotencyKey: OUTREACH_KEY });
    expect(data).toEqual(original);
  });

  it('accepts a cross-query add deduplicated to the existing Activity account selection', async () => {
    const priorCandidate = '90123456-9012-4012-8012-90123456abcd';
    const existing = preparationFixture({ candidate_id: priorCandidate, revision: 7, evaluation: null, evaluation_run_id: null,
      missing_fields: ['evaluation_missing'] });
    const client = new OutreachClient(async () => existing);
    await expect(client.add({ activityId: ACTIVITY_ID, data: { candidate_id: CANDIDATE_ID }, idempotencyKey: OUTREACH_KEY }))
      .resolves.toEqual(existing);
  });

  it.each([
    ['selections', { activityId: ACTIVITY_ID, limit: 0 }], ['selections', { activityId: ACTIVITY_ID, limit: 201 }],
    ['selections', { activityId: ACTIVITY_ID, offset: -1 }], ['selections', { activityId: ACTIVITY_ID, cancelled: true }],
    ['selections', { activityId: ACTIVITY_ID, includeCancelled: 'true' }],
    ['selection', { activityId: 'bad', id: SELECTION_ID }], ['selection', { activityId: ACTIVITY_ID, id: 'bad' }],
    ['update', { activityId: ACTIVITY_ID, id: SELECTION_ID, data: { expected_revision: -1, context_token: CONTEXT_TOKEN }, idempotencyKey: OUTREACH_KEY }],
    ['update', { activityId: ACTIVITY_ID, id: SELECTION_ID, data: { expected_revision: 0, context_token: 'A'.repeat(64) }, idempotencyKey: OUTREACH_KEY }],
    ['update', { activityId: ACTIVITY_ID, id: SELECTION_ID, data: { expected_revision: 0, context_token: CONTEXT_TOKEN, work_ids: Array(101).fill(WORK_ID) }, idempotencyKey: OUTREACH_KEY }],
    ['cancel', { activityId: ACTIVITY_ID, id: SELECTION_ID, data: { expected_revision: 0, context_token: CONTEXT_TOKEN }, idempotencyKey: OUTREACH_KEY }],
  ] as const)('rejects invalid or unknown %s input before dispatch', async (method, input) => {
    const request = vi.fn(), client = new OutreachClient(request);
    await expect((client[method] as (value: unknown) => Promise<unknown>)(input)).rejects.toMatchObject({ code: 'request_invalid' });
    expect(request).not.toHaveBeenCalled();
  });

  it('rejects empty, duplicate, oversized, or malformed atomic bulk changes before dispatch', async () => {
    const client = new OutreachClient(vi.fn());
    const invoke = (data: unknown) => client.bulk({ activityId: ACTIVITY_ID, data: data as never, idempotencyKey: OUTREACH_KEY });
    for (const data of [{}, { add_candidate_ids: [] }, { add_candidate_ids: [CANDIDATE_ID, CANDIDATE_ID.toUpperCase()] },
      { cancel_selections: [{ selection_id: SELECTION_ID, expected_revision: 0 }, { selection_id: SELECTION_ID, expected_revision: 1 }] },
      { add_candidate_ids: Array(601).fill(CANDIDATE_ID) }, { cancel_selections: [{ selection_id: 'bad', expected_revision: 0 }] }]) {
      await expect(invoke(data)).rejects.toMatchObject({ code: 'request_invalid' });
    }
  });

  it('treats an overlapping bulk receipt as an unknown mutation outcome', async () => {
    const client = new OutreachClient(async () => ({ added_selection_ids: [SELECTION_ID], cancelled_selection_ids: [SELECTION_ID] }));
    await expect(client.bulk({ activityId: ACTIVITY_ID, data: { add_candidate_ids: [CANDIDATE_ID] }, idempotencyKey: OUTREACH_KEY }))
      .rejects.toMatchObject({ code: 'outreach_outcome_unknown', retryable: false });
  });

  it('accepts 600 unique ordered freeze choices and rejects invalid membership', async () => {
    const ids = Array.from({ length: 600 }, (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`);
    const response = recipientBatchFixture({ recipient_count: 600, needs_repair_count: 600,
      recipients: ids.map((id, index) => ({ ...recipientBatchFixture().recipients[0], id,
        selection_id: id, snapshot: preparationFixture({ id, contact_options: [] }), preparation: preparationFixture({ id }) })) });
    const request = vi.fn().mockResolvedValue(response), client = new OutreachClient(request);
    await client.freeze({ activityId: ACTIVITY_ID, data: { request_id: REQUEST_ID,
      recipients: ids.map(selection_id => ({ selection_id, expected_revision: 3, context_token: CONTEXT_TOKEN })) }, idempotencyKey: OUTREACH_KEY });
    expect((request.mock.calls[0][0].body as { recipients: unknown[] }).recipients).toHaveLength(600);
    for (const recipients of [[], Array(601).fill({ selection_id: SELECTION_ID, expected_revision: 0, context_token: CONTEXT_TOKEN }),
      [{ selection_id: SELECTION_ID, expected_revision: 0, context_token: CONTEXT_TOKEN }, { selection_id: SELECTION_ID.toUpperCase(), expected_revision: 0, context_token: CONTEXT_TOKEN }]]) {
      await expect(client.freeze({ activityId: ACTIVITY_ID, data: { request_id: REQUEST_ID, recipients }, idempotencyKey: OUTREACH_KEY })).rejects.toMatchObject({ code: 'request_invalid' });
    }
  });

  it('strictly decodes complete preparation using Work and Evaluation decoders', () => {
    expect(decodePreparation(preparationFixture(), SELECTION_ID, ACTIVITY_ID)).toEqual(preparationFixture());
    for (const invalid of [
      { ...preparationFixture(), send_ready: true },
      { ...preparationFixture(), context_token: 'bad' },
      { ...preparationFixture(), extra: true },
      { ...preparationFixture(), works: [{ ...preparationFixture().works[0], metrics: [{ name: '', value: 2 }] }] },
      { ...preparationFixture(), evaluation: { ...preparationFixture().evaluation!, selected: true } },
      { ...preparationFixture(), evaluation: { ...preparationFixture().evaluation!, creator_id: SECOND_SELECTION_ID } },
      { ...preparationFixture(), evaluation: { ...preparationFixture().evaluation!, account_id: 'another-account' } },
    ]) expect(() => decodePreparation(invalid)).toThrowError(expect.objectContaining({ code: 'invalid_response' }));
  });

  it('accepts a same-Activity evaluation from another query for the selected account identity', () => {
    const laterCandidate = '91234567-9123-4123-8123-91234567abcd';
    const original = preparationFixture();
    const evaluation = { ...original.evaluation!, candidate_id: laterCandidate,
      match_brief: { ...original.evaluation!.match_brief!, candidate_id: laterCandidate } };
    expect(decodePreparation({ ...original, evaluation }, SELECTION_ID, ACTIVITY_ID).evaluation).toEqual(evaluation);
  });

  it('accepts frozen snapshots with an intentionally empty option list and a selected contact', () => {
    expect(decodeRecipientBatch(recipientBatchFixture(), RECIPIENT_BATCH_ID, ACTIVITY_ID).recipients[0].snapshot)
      .toMatchObject({ contact_options: [], selected_contact: { id: CONTACT_ID } });
  });

  it('rejects mismatched scope, membership, order, counts, and freeze receipts as unknown', async () => {
    const malformed = [
      recipientBatchFixture({ activity_id: SECOND_SELECTION_ID }),
      recipientBatchFixture({ request_id: SECOND_SELECTION_ID }),
      recipientBatchFixture({ send_ready_count: 1 as never }),
      recipientBatchFixture({ needs_repair_count: 0 }),
      recipientBatchFixture({ recipients: [{ ...recipientBatchFixture().recipients[0], selection_id: SECOND_SELECTION_ID }] }),
    ];
    for (const value of malformed) {
      const client = new OutreachClient(async () => value);
      await expect(client.freeze({ activityId: ACTIVITY_ID, data: { request_id: REQUEST_ID,
        recipients: [{ selection_id: SELECTION_ID, expected_revision: 3, context_token: CONTEXT_TOKEN }] }, idempotencyKey: OUTREACH_KEY }))
        .rejects.toMatchObject({ code: 'outreach_outcome_unknown', retryable: false });
    }
  });
});
