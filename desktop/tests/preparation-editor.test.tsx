// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { CreatorAPI, WorkDetail } from '../src/shared/creators';
import type { Preparation, PreparationContact } from '../src/shared/outreach';
import { PreparationEditor, PreparationSnapshot } from '../src/renderer/components/match/PreparationEditor';
import { CONTACT_ID, CREATOR_ID, WORK_ID, workFixture } from './creator-fixtures';
import { CONTEXT_TOKEN, preparationFixture } from './outreach-fixtures';

const SECOND_CONTACT_ID = '22222222-2222-4222-8222-222222222223';
const THIRD_CONTACT_ID = '22222222-2222-4222-8222-222222222224';
const FOURTH_CONTACT_ID = '22222222-2222-4222-8222-222222222225';
const NEW_WORK_ID = '44444444-4444-4444-8444-444444444445';
const LATER_WORK_ID = '44444444-4444-4444-8444-444444444446';
const MISSING_WORK_ID = '44444444-4444-4444-8444-444444444447';
const NEW_CONTEXT = 'b'.repeat(64);

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

function contact(id: string, email: string, status: PreparationContact['status'], sourceType = 'manual'): PreparationContact {
  return {
    id, email, purpose: 'Business', source_url: `https://example.com/${id}`, source_type: sourceType,
    source_fields: { email }, manual_overrides: {}, validation_state: status === 'invalid' ? 'invalid' : 'valid',
    identity_revision: 1, updated_at: '2026-09-08T00:00:00Z', status,
  };
}

function availableWork(id: string, name: string): WorkDetail {
  return { ...workFixture(), id, work_name: name, creator_id: CREATOR_ID, is_current_identity: true };
}

function setup(preparation: Preparation = preparationFixture(), saveResult = false, evaluationChoices: Array<{ id: string; label: string }> = []) {
  const works = vi.fn<CreatorAPI['works']>().mockResolvedValue({ ok: true, data: { items: [], total: 0, offset: 0, limit: 100 } });
  const props = {
    preparation, creators: { works }, active: true, busy: false, evaluationChoices,
    onSave: vi.fn(async () => saveResult), onOpenCreator: vi.fn(), onOpenExternal: vi.fn(), onRefresh: vi.fn(), onDirtyChange: vi.fn(),
  };
  const view = render(<PreparationEditor {...props}/>);
  return { ...view, props, works };
}

describe('PreparationEditor', () => {
  it('keeps a missing email as None, shows one explicit status-rich radio group, and emits only an explicitly selected eligible contact', async () => {
    const user = userEvent.setup();
    const eligible = contact(SECOND_CONTACT_ID, 'second@example.com', 'eligible', 'creator_page');
    const invalid = contact(CONTACT_ID, 'invalid@example.com', 'invalid');
    const inactive = contact(THIRD_CONTACT_ID, 'inactive@example.com', 'inactive');
    const historical = contact(FOURTH_CONTACT_ID, 'old@example.com', 'historical');
    const preparation = preparationFixture({ selected_contact: null, contact_status: 'not_selected', contact_options: [invalid, eligible, inactive, historical] });
    const { props } = setup(preparation);

    const group = screen.getByRole('group', { name: 'Email' });
    expect(within(group).getByRole('radio', { name: 'None' })).toBeChecked();
    expect(within(group).getByRole('radio', { name: /second@example.com/ })).not.toBeChecked();
    expect(within(group).getByText('Business · Creator page · Eligible')).toBeVisible();
    expect(within(group).getByRole('radio', { name: /invalid@example.com/ })).toBeDisabled();
    expect(within(group).getByRole('radio', { name: /inactive@example.com/ })).toBeDisabled();
    expect(within(group).getByRole('radio', { name: /old@example.com/ })).toBeDisabled();
    expect(props.onSave).not.toHaveBeenCalled();

    await user.click(within(group).getByRole('radio', { name: /second@example.com/ }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(props.onSave).toHaveBeenCalledOnce();
    expect(props.onSave).toHaveBeenCalledWith({ expected_revision: 3, context_token: CONTEXT_TOKEN, contact_id: SECOND_CONTACT_ID });
  });

  it('keeps the observed address version selected until the user explicitly reselects the changed current source', async () => {
    const user = userEvent.setup();
    const observed = contact(CONTACT_ID, 'creator@example.com', 'eligible', 'profile_v1');
    const current = { ...contact(CONTACT_ID, 'creator@example.com', 'eligible', 'profile_v2'), updated_at: '2026-09-09T00:00:00Z' };
    const { props } = setup(preparationFixture({ selected_contact: observed, contact_options: [current], contact_status: 'changed' }));

    expect(screen.getByRole('radio', { name: 'Saved version creator@example.com' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Current version creator@example.com' })).not.toBeChecked();
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: 'Current version creator@example.com' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(props.onSave).toHaveBeenCalledWith({ expected_revision: 3, context_token: CONTEXT_TOKEN, contact_id: CONTACT_ID });

    await user.click(screen.getByText('Source details for creator@example.com'));
    await user.click(screen.getByRole('button', { name: 'Open source for creator@example.com' }));
    expect(props.onOpenExternal).toHaveBeenCalledWith(current.source_url);
  });

  it('explicitly confirms the current public name, pages current works on demand, preserves missing IDs, and can clear the recorded evaluation', async () => {
    const user = userEvent.setup();
    const related = { ...preparationFixture().works[0], relation: 'related_content' as const, evidence_status: 'metadata_only' as const };
    const preparation = preparationFixture({ public_name_confirmed: false, name_confirmed_at: null, works: [related], missing_work_ids: [MISSING_WORK_ID] });
    const { props, works } = setup(preparation);
    works.mockResolvedValueOnce({ ok: true, data: { items: [availableWork(WORK_ID, 'A recorded work'), availableWork(NEW_WORK_ID, 'New work')], total: 3, offset: 0, limit: 100 } })
      .mockResolvedValueOnce({ ok: true, data: { items: [availableWork(LATER_WORK_ID, 'Later work')], total: 3, offset: 2, limit: 100 } });

    expect(screen.getByText('Other recorded content')).toBeVisible();
    expect(screen.getAllByText('Metadata only')[0]).toBeVisible();
    expect(screen.getByRole('checkbox', { name: `Keep unavailable work ${MISSING_WORK_ID}` })).toBeChecked();
    expect(screen.getByText('Potential gameplay fit.')).toBeVisible();
    expect(screen.getByRole('combobox', { name: 'Match brief' })).toHaveValue(preparation.evaluation_run_id);
    expect(works).not.toHaveBeenCalled();

    await user.click(screen.getByRole('button', { name: 'Choose known works' }));
    await waitFor(() => expect(works).toHaveBeenCalledWith({ creatorId: CREATOR_ID, limit: 100, offset: 0 }));
    expect(await screen.findByRole('checkbox', { name: 'Use New work' })).not.toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Load more works' }));
    await waitFor(() => expect(works).toHaveBeenLastCalledWith({ creatorId: CREATOR_ID, limit: 100, offset: 2 }));
    expect(await screen.findByRole('checkbox', { name: 'Use Later work' })).toBeVisible();

    await user.click(screen.getByRole('checkbox', { name: `Keep unavailable work ${MISSING_WORK_ID}` }));
    await user.click(screen.getByRole('checkbox', { name: 'Use New work' }));
    await user.selectOptions(screen.getByRole('combobox', { name: 'Match brief' }), '');
    await user.click(screen.getByRole('checkbox', { name: 'Confirm “Creator” as public name' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));

    expect(props.onSave).toHaveBeenCalledWith({
      expected_revision: 3, context_token: CONTEXT_TOKEN, confirm_public_name: true,
      work_ids: [WORK_ID, NEW_WORK_ID], evaluation_run_id: null,
    });
    expect(screen.queryByText(/sender (viewed|watched)/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/played this game/i)).not.toBeInTheDocument();
  });

  it('keeps a fresh selection at no evaluation until an existing Match brief is explicitly chosen', async () => {
    const user = userEvent.setup();
    const preparation = preparationFixture({ evaluation: null, evaluation_run_id: null, missing_fields: ['evaluation_missing'] });
    const choices = [{ id: '12345678-1234-4234-8234-123456789abc', label: 'Sep 8 · Current evaluation' }];
    const { props } = setup(preparation, false, choices);
    const select = screen.getByRole('combobox', { name: 'Match brief' });
    expect(select).toHaveValue(''); expect(props.onSave).not.toHaveBeenCalled();
    await user.selectOptions(select, choices[0].id);
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(props.onSave).toHaveBeenCalledWith({ expected_revision: 3, context_token: CONTEXT_TOKEN, evaluation_run_id: choices[0].id });
  });

  it('retains the chosen subset and permits an explicit retry when the on-demand works read fails', async () => {
    const user = userEvent.setup(); const { works } = setup();
    works.mockResolvedValueOnce({ ok: false, error: { code: 'network_error', message: 'Known works unavailable', retryable: true } })
      .mockResolvedValueOnce({ ok: true, data: { items: [availableWork(NEW_WORK_ID, 'Recovered work')], total: 1, offset: 0, limit: 100 } });
    await user.click(screen.getByRole('button', { name: 'Choose known works' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Known works unavailable');
    expect(screen.getByRole('checkbox', { name: 'Use A recorded work' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Try works again' }));
    expect(await screen.findByRole('checkbox', { name: 'Use Recovered work' })).toBeVisible();
    expect(works).toHaveBeenCalledTimes(2);
  });

  it('retries the exact failed works page after a load-more failure', async () => {
    const user = userEvent.setup(); const { works } = setup();
    works.mockResolvedValueOnce({ ok: true, data: { items: [availableWork(NEW_WORK_ID, 'First new work'), availableWork(LATER_WORK_ID, 'Second new work')], total: 3, offset: 0, limit: 100 } })
      .mockResolvedValueOnce({ ok: false, error: { code: 'network_error', message: 'Next page unavailable', retryable: true } })
      .mockResolvedValueOnce({ ok: true, data: { items: [availableWork('44444444-4444-4444-8444-444444444448', 'Recovered later work')], total: 3, offset: 2, limit: 100 } });

    await user.click(screen.getByRole('button', { name: 'Choose known works' }));
    await screen.findByRole('checkbox', { name: 'Use First new work' });
    await user.click(screen.getByRole('button', { name: 'Load more works' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Next page unavailable');
    await user.click(screen.getByRole('button', { name: 'Try works again' }));

    expect(await screen.findByRole('checkbox', { name: 'Use Recovered later work' })).toBeVisible();
    expect(works).toHaveBeenLastCalledWith({ creatorId: CREATOR_ID, limit: 100, offset: 2 });
  });

  it('offers Creator repair for a missing public name and retains edits across inspection and a failed save', async () => {
    const user = userEvent.setup(); const preparation = preparationFixture({ public_name: null, public_name_confirmed: false, name_confirmed_at: null });
    const { props } = setup(preparation, false);
    await user.click(screen.getByRole('button', { name: 'Edit public name in Creator' }));
    expect(props.onOpenCreator).toHaveBeenCalledWith(preparation.creator_id, 'overview');
    await user.click(screen.getByRole('radio', { name: 'None' }));
    expect(props.onDirtyChange).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole('button', { name: 'View email records' }));
    expect(props.onOpenCreator).toHaveBeenLastCalledWith(preparation.creator_id, 'contacts');
    expect(screen.getByRole('radio', { name: 'None' })).toBeChecked();
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(props.onSave).toHaveBeenCalledWith({ expected_revision: 3, context_token: CONTEXT_TOKEN, contact_id: null });
    expect(screen.getByRole('radio', { name: 'None' })).toBeChecked();
    expect(props.onDirtyChange).toHaveBeenLastCalledWith(true);
  });

  it('preserves a dirty observed draft when newer props arrive and only discards it through an explicit reload or Cancel', async () => {
    const user = userEvent.setup(); const initial = preparationFixture();
    const { props, rerender } = setup(initial);
    await user.click(screen.getByRole('radio', { name: 'None' }));
    const incoming = preparationFixture({ revision: 4, context_token: NEW_CONTEXT, selected_contact: contact(SECOND_CONTACT_ID, 'new@example.com', 'eligible'), contact_options: [contact(SECOND_CONTACT_ID, 'new@example.com', 'eligible')] });
    rerender(<PreparationEditor {...props} preparation={incoming}/>);

    expect(screen.getByRole('radio', { name: 'None' })).toBeChecked();
    expect(screen.getByRole('status')).toHaveTextContent('Preparation changed');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(props.onSave).toHaveBeenLastCalledWith({ expected_revision: 3, context_token: CONTEXT_TOKEN, contact_id: null });
    await user.click(screen.getByRole('button', { name: 'Discard edits and reload' }));
    expect(props.onRefresh).toHaveBeenCalledOnce();
    expect(screen.getByRole('radio', { name: /new@example.com/ })).toBeChecked();
    expect(props.onDirtyChange).toHaveBeenLastCalledWith(false);

    await user.click(screen.getByRole('radio', { name: 'None' }));
    await user.click(screen.getByRole('button', { name: 'Cancel changes' }));
    expect(screen.getByRole('radio', { name: /new@example.com/ })).toBeChecked();
    expect(props.onDirtyChange).toHaveBeenLastCalledWith(false);
  });

  it('requests a preparation refresh without discarding the dirty observed draft', async () => {
    const user = userEvent.setup(); const { props } = setup();
    await user.click(screen.getByRole('radio', { name: 'None' }));

    await user.click(screen.getByRole('button', { name: 'Refresh preparation' }));

    expect(props.onRefresh).toHaveBeenCalledOnce();
    expect(screen.getByRole('radio', { name: 'None' })).toBeChecked();
    expect(props.onDirtyChange).toHaveBeenLastCalledWith(true);
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled();
  });

  it('waits for a fresh parent preparation after a successful save before clearing dirty state', async () => {
    const user = userEvent.setup(); const initial = preparationFixture();
    const { props, rerender } = setup(initial, true);
    await user.click(screen.getByRole('radio', { name: 'None' }));
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    expect(props.onDirtyChange).toHaveBeenLastCalledWith(true);
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled();

    const fresh = preparationFixture({ revision: 4, context_token: NEW_CONTEXT, selected_contact: null, contact_status: 'not_selected' });
    rerender(<PreparationEditor {...props} preparation={fresh}/>);
    await waitFor(() => expect(props.onDirtyChange).toHaveBeenLastCalledWith(false));
    expect(screen.getByRole('radio', { name: 'None' })).toBeChecked();
    expect(screen.queryByText('Preparation changed')).not.toBeInTheDocument();
  });

  it('keeps the immutable snapshot concise and free of edit or send controls', () => {
    render(<PreparationSnapshot preparation={preparationFixture({ missing_fields: ['email_missing', 'evidence_missing'] })}/>);
    const snapshot = screen.getByRole('region', { name: 'Original preparation snapshot' });
    expect(within(snapshot).getByText('Creator')).toBeVisible();
    expect(within(snapshot).getByText('creator@example.com')).toBeVisible();
    expect(within(snapshot).getByText('Email missing')).toBeVisible();
    expect(within(snapshot).getByText('Evidence missing')).toBeVisible();
    expect(within(snapshot).queryByRole('button')).not.toBeInTheDocument();
    expect(within(snapshot).queryByRole('checkbox')).not.toBeInTheDocument();
    expect(within(snapshot).queryByText(/send/i)).not.toBeInTheDocument();
  });

  it('reveals exact immutable name, contact, work, missing-work, and evaluation evidence only inside snapshot details', async () => {
    const user = userEvent.setup();
    const base = preparationFixture(), frozenContact = {
      ...base.selected_contact!, purpose: 'Partnership', source_type: 'creator_page', source_url: 'https://example.com/frozen-contact',
      identity_revision: 2, updated_at: '2026-09-07T12:30:00Z',
    };
    const frozenWork = {
      ...base.works[0], content_title: 'Frozen historical work', source_url: 'https://example.com/frozen-work',
      revision: 7, identity_revision: 2, relation: 'related_content' as const, evidence_status: 'recorded_evidence' as const,
      evidence_excerpt: 'Recorded excerpt', verification_notes: 'Recorded verification note',
    };
    render(<PreparationSnapshot preparation={preparationFixture({ selected_contact: frozenContact, contact_options: [], works: [frozenWork], missing_work_ids: [MISSING_WORK_ID] })}/>);
    const snapshot = screen.getByRole('region', { name: 'Original preparation snapshot' });
    expect(within(snapshot).getByText('Frozen historical work')).not.toBeVisible();
    await user.click(within(snapshot).getByText('Recorded preparation details'));
    expect(within(snapshot).getByText('Name confirmed')).toBeVisible();
    expect(within(snapshot).getByText('Sep 8, 2026')).toBeVisible();
    expect(within(snapshot).getByText('Partnership · Creator page · Eligible')).toBeVisible();
    expect(within(snapshot).getByText('https://example.com/frozen-contact')).toBeVisible();
    expect(within(snapshot).getByText('Frozen historical work')).toBeVisible();
    expect(within(snapshot).getByText('Record revision 7 · Identity revision 2')).toBeVisible();
    expect(within(snapshot).getByText('https://example.com/frozen-work')).toBeVisible();
    expect(within(snapshot).getByText('Recorded excerpt')).toBeVisible();
    expect(within(snapshot).getByText('Recorded verification note')).toBeVisible();
    expect(within(snapshot).getByText(MISSING_WORK_ID)).toBeVisible();
    expect(within(snapshot).getByText('Potential gameplay fit.')).toBeVisible();
    expect(within(snapshot).getByText('Game fixture gameplay')).toBeVisible();
    expect(within(snapshot).queryByRole('button')).not.toBeInTheDocument();
    expect(within(snapshot).queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
