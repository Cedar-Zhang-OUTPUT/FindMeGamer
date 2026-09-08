// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { DeliveryEditor, type DeliveryEditorProps } from '../src/renderer/components/match/DeliveryEditor';
import { deliveryFixture, sendBatchFixture } from './sending-fixtures';
afterEach(cleanup);
function setup(patch: Partial<DeliveryEditorProps> = {}): DeliveryEditorProps {
  const first = deliveryFixture({ state: 'unknown', attempt: 2, error_code: 'smtp_outcome_unknown' });
  const second = deliveryFixture({ id: 'second', draft_id: 'second-draft', recipient_snapshot_id: 'second-recipient', state: 'failed', attempt: 1, retryable: true, snapshot: { ...first.snapshot, draft_id: 'second-draft', recipient_snapshot_id: 'second-recipient', recipient_email: 'second@example.test', values: { ...first.snapshot.values!, channelName: 'Second channel' } } });
  return { batch: sendBatchFixture({ deliveries: [first, second] }), current: true, busy: false, onRetry: vi.fn(async () => true), onResolve: vi.fn(async () => false), onDirtyChange: vi.fn(), ...patch };
}
const note = (value: string) => fireEvent.change(screen.getByRole('textbox', { name: 'Verification source note' }), { target: { value } });
it('shows frozen addresses and HTML and never offers normal retry for an unknown result', () => {
  const p = setup(); render(<DeliveryEditor {...p} />);
  expect(screen.getByText('synthetic-sender@example.test')).toBeVisible();
  expect(within(screen.getByRole('navigation', { name: 'Deliveries' })).getAllByRole('button')).toHaveLength(2);
  expect(screen.getByTitle('Frozen email preview')).toHaveAttribute('sandbox', '');
  expect(screen.getByTitle('Frozen email preview')).toHaveAttribute('srcdoc', expect.stringContaining(p.batch.deliveries[0].snapshot.html!));
  expect(screen.queryByRole('button', { name: 'Retry delivery' })).not.toBeInTheDocument();
  expect(screen.getByRole('combobox', { name: 'Verified outcome' })).toHaveValue('');
  expect(screen.getByRole('button', { name: 'Record verified outcome' })).toBeDisabled(); expect(p.onRetry).not.toHaveBeenCalled();
});
it('requires explicit outcome and source note; recording not sent never sends or retries', async () => {
  const p = setup(); render(<DeliveryEditor {...p} />);
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Verified outcome' }), 'not_sent');
  expect(screen.getByRole('button', { name: 'Record verified outcome' })).toBeDisabled();
  note('Capture operator confirmed no submission.');
  expect(screen.getByText('Recording not sent does not resend the email.')).toBeVisible();
  await userEvent.click(screen.getByRole('button', { name: 'Record verified outcome' }));
  expect(p.onResolve).toHaveBeenCalledWith(p.batch.deliveries[0].id, { expected_attempt: 2, outcome: 'not_sent', source_note: 'Capture operator confirmed no submission.' });
  expect(p.onRetry).not.toHaveBeenCalled(); expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue('Capture operator confirmed no submission.');
});
it('retains per-delivery notes across selection, polling, and a non-current detour without resetting aggregate dirty state', async () => {
  const p = setup(); const view = render(<DeliveryEditor {...p} />); note('Keep first note.');
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Deliveries' })).getAllByRole('button')[1]);
  expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
  await userEvent.click(within(screen.getByRole('navigation', { name: 'Deliveries' })).getAllByRole('button')[0]);
  view.rerender(<DeliveryEditor {...p} current={false} batch={structuredClone(p.batch)} />);
  expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue('Keep first note.');
  expect(screen.getByRole('textbox', { name: 'Verification source note' })).toBeDisabled();
  view.rerender(<DeliveryEditor {...p} />); expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue('Keep first note.');
});
it('requires an explicit new attempt binding, retaining the note but resetting the old outcome', async () => {
  const p = setup(); const view = render(<DeliveryEditor {...p} />); note('Earlier evidence.');
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Verified outcome' }), 'sent');
  const updated = { ...p.batch, deliveries: p.batch.deliveries.map((row, i) => i ? row : { ...row, attempt: 3 }) };
  view.rerender(<DeliveryEditor {...p} batch={updated} />);
  expect(screen.getByRole('button', { name: 'Record verified outcome' })).toBeDisabled();
  expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue('Earlier evidence.');
  await userEvent.click(screen.getByRole('button', { name: 'Use current attempt' }));
  expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue('Earlier evidence.'); expect(screen.getByRole('combobox', { name: 'Verified outcome' })).toHaveValue('');
});
it('retries only a retryable definite failure or explicitly dispatches queued content', async () => {
  const p = setup(), view = render(<DeliveryEditor {...p} />); await userEvent.click(within(screen.getByRole('navigation', { name: 'Deliveries' })).getAllByRole('button')[1]);
  await userEvent.click(screen.getByRole('button', { name: 'Retry delivery' })); expect(p.onRetry).toHaveBeenCalledWith('second');
  view.rerender(<DeliveryEditor {...p} batch={{ ...p.batch, deliveries: [deliveryFixture()] }} />);
  await userEvent.click(screen.getByRole('button', { name: 'Dispatch queued' })); expect(p.onRetry).toHaveBeenCalledTimes(2);
  view.rerender(<DeliveryEditor {...p} batch={{ ...p.batch, deliveries: [deliveryFixture({ state: 'failed', retryable: false })] }} />);
  expect(screen.queryByRole('button', { name: 'Retry delivery' })).not.toBeInTheDocument();
});
it('distinguishes SMTP acceptance from a manually recorded sent outcome and never retries sent', () => {
  const p = setup({ batch: sendBatchFixture({ deliveries: [deliveryFixture({ state: 'sent' })] }) }); const view = render(<DeliveryEditor {...p} />);
  expect(screen.getAllByText('Accepted by SMTP').length).toBeGreaterThan(0); expect(screen.queryByRole('button', { name: 'Retry delivery' })).not.toBeInTheDocument();
  view.rerender(<DeliveryEditor {...p} batch={sendBatchFixture({ deliveries: [deliveryFixture({ state: 'sent', resolution: { outcome: 'sent', attempt: 0, source_note: 'Capture log', at: '2026-09-08T00:00:00Z' } })] })} />);
  expect(screen.getAllByText('Recorded as sent').length).toBeGreaterThan(0);
});
it('bounds verification notes and clears only a successful submitted session', async () => {
  const p = setup({ onResolve: vi.fn(async () => true) }); render(<DeliveryEditor {...p} />);
  expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveAttribute('maxlength', '2000');
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Verified outcome' }), 'sent'); note('x'.repeat(2001));
  expect(screen.getByRole('button', { name: 'Record verified outcome' })).toBeDisabled(); note('Verified in capture.');
  await userEvent.click(screen.getByRole('button', { name: 'Record verified outcome' }));
  await waitFor(() => expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue(''));
  expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
});
it('does not erase a retained old-attempt note when a late success arrives after the delivery advances', async () => {
  let finish!: (value: boolean) => void;
  const p = setup({ onResolve: vi.fn(() => new Promise<boolean>(resolve => { finish = resolve; })) });
  const view = render(<DeliveryEditor {...p} />); note('Evidence from attempt two.');
  await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Verified outcome' }), 'sent');
  fireEvent.click(screen.getByRole('button', { name: 'Record verified outcome' }));
  fireEvent.click(screen.getByRole('button', { name: 'Record verified outcome' })); expect(p.onResolve).toHaveBeenCalledTimes(1);
  view.rerender(<DeliveryEditor {...p} batch={{ ...p.batch, deliveries: p.batch.deliveries.map((row, i) => i ? row : { ...row, attempt: 3 }) }} />);
  await act(async () => { finish(true); });
  expect(screen.getByRole('textbox', { name: 'Verification source note' })).toHaveValue('Evidence from attempt two.');
  expect(screen.getByRole('button', { name: 'Use current attempt' })).toBeEnabled(); expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
});
