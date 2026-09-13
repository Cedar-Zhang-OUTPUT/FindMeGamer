// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { SenderFactsEditor } from '../src/renderer/components/match/SenderFactsEditor';
import { compositionFixture, draftFixture, draftValues } from './drafts-fixtures';
afterEach(cleanup);
const complete = () => draftFixture({ status: 'succeeded', values: draftValues, rendered: { subject: 'Fixture', html: '<p>Fixture</p>', text: 'Fixture', fixed_hash: 'a'.repeat(64) }, sender_facts_valid: true, sender_facts: { following: true, enjoyed: true, liked: true } });
const composition = () => compositionFixture({ drafts: [complete(), draftFixture({ id: '99999999-9999-4999-8999-999999999999', input_order: 1 })], recipient_count: 2 });
it('shows the saved override being confirmed, separately from its source identity', async () => {
  const draft = complete(); draft.values = { ...draftValues, channelName: 'Personalized channel', reference: 'Chosen reference', observation: 'Authored observation.' };
  render(<SenderFactsEditor composition={compositionFixture({ drafts: [draft] })} busy={false} current onSave={vi.fn()} />);
  await userEvent.click(screen.getByText('Sender confirmations'));
  expect(screen.getByRole('checkbox', { name: 'Personalized channel' })).toBeVisible();
  await userEvent.click(screen.getByRole('checkbox', { name: 'Personalized channel' }));
  expect(screen.getByText('Chosen reference')).toBeVisible();
  expect(screen.getByText('Authored observation.')).toBeVisible();
  expect(screen.getByText('Source: Fixture Channel')).toBeVisible();
  expect(screen.getByRole('checkbox', { name: 'I follow these channels' })).not.toBeChecked();
});
it('starts empty and false, chooses only completed members, and submits explicit false facts', async () => {
  const onSave = vi.fn(async () => true); render(<SenderFactsEditor composition={composition()} busy={false} current onSave={onSave} />);
  await userEvent.click(screen.getByText('Sender confirmations')); expect(screen.getByRole('checkbox', { name: 'I follow these channels' })).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'Save confirmations for 0' })).toBeDisabled();
  await userEvent.click(screen.getByRole('button', { name: 'Select completed' }));
  await userEvent.click(screen.getByRole('button', { name: 'Save confirmations for 1' }));
  expect(onSave).toHaveBeenCalledWith({ members: [{ draft_id: complete().id, expected_revision: 0, context_token: 'a'.repeat(64) }], following: false, enjoyed: false, liked: false });
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save confirmations for 0' })).toBeDisabled());
});
it('retains chosen versions and facts across collapse, stale polling and failed saving', async () => {
  const onSave = vi.fn(async () => false), onDirtyChange = vi.fn(); const p = { composition: composition(), busy: false, current: true, onSave, onDirtyChange }; const view = render(<SenderFactsEditor {...p} />);
  await userEvent.click(screen.getByText('Sender confirmations')); await userEvent.click(screen.getByRole('button', { name: 'Select completed' })); await userEvent.click(screen.getByRole('checkbox', { name: 'I follow these channels' }));
  await userEvent.click(screen.getByRole('button', { name: 'Save confirmations for 1' })); expect(screen.getByRole('checkbox', { name: 'I follow these channels' })).toBeChecked();
  await userEvent.click(screen.getByText('Sender confirmations')); await userEvent.click(screen.getByText('Sender confirmations'));
  view.rerender(<SenderFactsEditor {...p} composition={compositionFixture({ drafts: [{ ...complete(), revision: 1 }] })} />);
  expect(screen.getByRole('button', { name: 'Save confirmations for 1' })).toBeDisabled(); expect(screen.getByText(/changed since you selected/i)).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'I follow these channels' })).toBeChecked(); await userEvent.click(screen.getByRole('button', { name: 'Reload choices and clear confirmations' }));
  expect(screen.getByRole('checkbox', { name: 'I follow these channels' })).not.toBeChecked(); expect(onDirtyChange).toHaveBeenLastCalledWith(false);
});
it('blocks detached/current-false writes and duplicate async submits', async () => {
  let finish!: (v: boolean) => void; const onSave = vi.fn(() => new Promise<boolean>(r => { finish = r; })); const p = { composition: composition(), busy: false, current: true, onSave }; const view = render(<SenderFactsEditor {...p} />);
  await userEvent.click(screen.getByText('Sender confirmations')); await userEvent.click(screen.getByRole('button', { name: 'Select completed' }));
  view.rerender(<SenderFactsEditor {...p} current={false} />); expect(screen.getByRole('button', { name: 'Save confirmations for 1' })).toBeDisabled();
  view.rerender(<SenderFactsEditor {...p} />); await userEvent.dblClick(screen.getByRole('button', { name: 'Save confirmations for 1' })); expect(onSave).toHaveBeenCalledOnce(); finish(true);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Save confirmations for 0' })).toBeDisabled());
});
