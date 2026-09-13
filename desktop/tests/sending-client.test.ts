import { expect, it, vi } from 'vitest';
import { SendingClient } from '../src/main/sending-client';
import { decodeBatch, decodeDelivery, decodeQualification } from '../src/main/sending-validation';
import { deliveryFixture, qualificationFixture, qualifiedMemberFixture, sendBatchFixture, sendingIds } from './sending-fixtures';
const id = '11111111-1111-4111-8111-111111111111';
it('never accepts unfinished draft text as an eligible sending snapshot', () => {
  const member = qualifiedMemberFixture();
  const values = { ...member.values!, firstName: '' };
  const html = member.html!.replace('>Ari</span>', '></span>');
  const text = member.text!.replace('Ari', '');
  expect(() => decodeQualification(qualificationFixture({ members: [{ ...member, values, html, text }] }))).toThrow();
});
it('can display incomplete values for blocked qualification without treating them as sendable', () => {
  const original = qualifiedMemberFixture();
  const member = { ...original, status: 'needs_repair' as const, missing_fields: ['firstName_missing'], values: { ...original.values!, firstName: '' }, html: original.html!.replace('>Ari</span>', '></span>'), text: original.text!.replace('Ari', '') };
  const qualification = qualificationFixture({ members: [member], eligible_count: 0, repair_count: 1, send_ready: false });
  expect(decodeQualification(qualification).members[0].values?.firstName).toBe('');
  expect(decodeQualification(qualification).send_ready).toBe(false);
});
it('rejects incomplete observation punctuation in eligible and historical delivery snapshots', () => {
  const original = qualifiedMemberFixture();
  const observation = original.values!.observation.slice(0, -1);
  const member = { ...original, values: { ...original.values!, observation }, html: original.html!.replace(original.values!.observation, observation), text: original.text!.replace(original.values!.observation, observation) };
  expect(() => decodeQualification(qualificationFixture({ members: [member] }))).toThrow();
  const delivery = deliveryFixture();
  expect(() => decodeDelivery({ ...delivery, snapshot: { ...delivery.snapshot, ...member } })).toThrow();
});
it('qualifies read-only with no key and keeps malformed qualify responses out of unknown writes', async () => {
  const request = vi.fn().mockResolvedValue({});
  await expect(new SendingClient(request).qualify({ compositionId: id, data: { excluded: [] } })).rejects.toMatchObject({ code: 'invalid_response' });
  expect(request).toHaveBeenCalledWith({ method: 'POST', path: `/api/v2/outreach/compositions/${id}/qualification`, body: { excluded: [] } });
});
it('sends exact frozen UUID/token/exclusions/key and treats malformed send receipt as unknown', async () => {
  const request = vi.fn().mockResolvedValue({}), data = { request_id: id, qualification_token: 'a'.repeat(64), excluded: [] };
  await expect(new SendingClient(request).send({ compositionId: id, data, idempotencyKey: 'fixture-key' })).rejects.toMatchObject({ code: 'sending_write_unknown' });
  expect(request).toHaveBeenCalledWith({ method: 'POST', path: `/api/v2/outreach/compositions/${id}/send-batches`, body: data, idempotencyKey: 'fixture-key' });
});
it('validates full-N counts, unique members, eligible addresses, sender and immutable ordered snapshots', () => {
  expect(decodeBatch(sendBatchFixture())).toEqual(sendBatchFixture());
  for (const change of [{ total_count: 2 }, { send_ready: false }, { eligible_count: 0 }, { members: [qualifiedMemberFixture(), qualifiedMemberFixture()], total_count: 2, eligible_count: 2 }, { sender: { address: 'one@example.test,two@example.test', name: null, reply_to: null } }]) expect(() => decodeQualification({ ...qualificationFixture(), ...change })).toThrow();
  for (const change of [{ deliveries: [] }, { deliveries: [deliveryFixture({ snapshot: { ...deliveryFixture().snapshot, text: 'Changed frozen text' } })] }, { deliveries: [deliveryFixture({ snapshot: { ...deliveryFixture().snapshot, sender: { address: 'other@example.test', name: null, reply_to: null } } })] }, { deliveries: [deliveryFixture({ draft_id: sendingIds.game })] }]) expect(() => decodeBatch({ ...sendBatchFixture(), ...change })).toThrow();
  expect(() => decodeDelivery(deliveryFixture({ snapshot: { ...deliveryFixture().snapshot, recipient_email: 'one@example.test;two@example.test' } }))).toThrow();
  expect(() => decodeDelivery(deliveryFixture({ snapshot: { ...deliveryFixture().snapshot, html: deliveryFixture().snapshot.html!.replace('Hi', 'Bye') } }))).toThrow();
  expect(() => decodeDelivery(deliveryFixture({ error_code: 'raw recipient@example.test failure' }))).toThrow();
});
it('validates attempt/status/resolution and preserves exact reads/retry/resolve routes without headers', async () => {
  for (const change of [{ attempt: -1 }, { attempt: 0.5 }, { state: 'sent', sent_at: null }, { state: 'unknown', attempt: 1, retryable: true }]) expect(() => decodeDelivery({ ...deliveryFixture(), ...change })).toThrow();
  const resolved = deliveryFixture({ state: 'failed', attempt: 1, retryable: true, failed_at: '2026-09-08T01:00:00Z', error_code: 'submission_verified_not_sent', resolution: { outcome: 'not_sent', source_note: 'Fixture verification', at: '2026-09-08T01:00:00Z', attempt: 1 } });
  const request = vi.fn().mockResolvedValueOnce({ items: [sendBatchFixture()], total: 1, offset: 0, limit: 100 }).mockResolvedValueOnce(sendBatchFixture()).mockResolvedValueOnce(deliveryFixture({ attempt: 1 })).mockResolvedValueOnce(resolved);
  const client = new SendingClient(request); await client.batches({ activityId: sendingIds.activity, limit: 100 }); await client.batch(sendingIds.batch); await client.retry({ id: sendingIds.delivery, data: { expected_attempt: 1 } }); await client.resolve({ id: sendingIds.delivery, data: { expected_attempt: 1, outcome: 'not_sent', source_note: 'Fixture verification' } });
  expect(request.mock.calls.map(v => v[0])).toEqual([
    { method: 'GET', path: `/api/v2/activities/${sendingIds.activity}/send-batches`, query: { offset: '0', limit: '100' } },
    { method: 'GET', path: `/api/v2/outreach/send-batches/${sendingIds.batch}` },
    { method: 'POST', path: `/api/v2/outreach/deliveries/${sendingIds.delivery}/retry`, body: { expected_attempt: 1 } },
    { method: 'POST', path: `/api/v2/outreach/deliveries/${sendingIds.delivery}/resolve`, body: { expected_attempt: 1, outcome: 'not_sent', source_note: 'Fixture verification' } },
  ]);
});
it('does not accept another qualification token/exclusion or a page from another Activity', async () => {
  const request = vi.fn().mockResolvedValue(sendBatchFixture()), client = new SendingClient(request);
  await expect(client.send({ compositionId: sendingIds.composition, data: { request_id: sendingIds.request, qualification_token: 'e'.repeat(64), excluded: [] }, idempotencyKey: 'fixture-key' })).rejects.toMatchObject({ code: 'sending_write_unknown' });
  await expect(client.send({ compositionId: sendingIds.composition, data: { request_id: sendingIds.request, qualification_token: qualificationFixture().qualification_token, excluded: [{ draft_id: sendingIds.draft, reason: 'Excluded' }] }, idempotencyKey: 'fixture-key' })).rejects.toMatchObject({ code: 'sending_write_unknown' });
  request.mockResolvedValue({ items: [sendBatchFixture()], total: 1, offset: 0, limit: 50 }); await expect(client.batches({ activityId: sendingIds.game })).rejects.toMatchObject({ code: 'invalid_response' });
});
