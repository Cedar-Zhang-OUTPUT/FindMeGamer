// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { useState } from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CreatorForm } from '../src/renderer/components/creators/CreatorForm';
import { ContactForm } from '../src/renderer/components/creators/ContactForm';
import { WorkForm } from '../src/renderer/components/creators/WorkForm';
import { draftFrom, makePayload, type EditContext } from '../src/renderer/components/creators/creatorDraft';
import { creatorFormFixture, contactFormFixture, workFormFixture } from './creator-form-fixtures';
import { gameFixture } from './game-fixtures';
import type { DesktopBridge } from '../src/shared/bridge';
import { CREATOR_FIELDS, CONTACT_FIELDS, WORK_FIELDS } from '../src/shared/creators';
import { fieldLabel } from '../src/renderer/components/creators/creatorDraft';

afterEach(cleanup);
const games = (): Pick<DesktopBridge, 'games'> => ({ games: { list: vi.fn(async () => ({ ok: true as const, data: { items: [gameFixture('Tide')], offset: 0, total: 21, limit: 20 } })), detail: vi.fn(async () => ({ ok: true as const, data: gameFixture('Existing game') })), create: vi.fn(), update: vi.fn() } });
function Harness({ context, api = games(), disabled = false }: { context: EditContext; api?: Pick<DesktopBridge, 'games'>; disabled?: boolean }) {
  const [draft, onChange] = useState(() => draftFrom(context));
  const props = { context, draft, onChange, disabled, errors: {} };
  return <div className="creators">{context.kind === 'creator' ? <CreatorForm {...props}/> : context.kind === 'contact' ? <ContactForm {...props}/> : <WorkForm {...props} api={api}/>}<output data-testid="payload">{JSON.stringify(makePayload(context, draft))}</output></div>;
}
describe('creator pure forms', () => {
  it('clears public-name confirmation on a new name and lets the user explicitly reconfirm', async () => {
    render(<Harness context={{ kind: 'creator', base: creatorFormFixture() }}/>); const user = userEvent.setup();
    await user.click(screen.getByText('Display details', { selector: 'summary' }));
    const input = screen.getByLabelText('Public name'); await user.clear(input); await user.type(input, 'New name');
    expect(screen.getByLabelText('Public name confirmed')).not.toBeChecked();
    expect(screen.getByTestId('payload')).toHaveTextContent('"public_name_confirmed":false');
    await user.click(screen.getByLabelText('Public name confirmed')); expect(screen.getByLabelText('Public name confirmed')).toBeChecked();
    expect(JSON.parse(screen.getByTestId('payload').textContent!)).toEqual({ expected_revision: 7, public_name: 'New name', public_name_confirmed: true });
    expect(screen.getByLabelText('Public name')).toBeVisible();
    expect(screen.queryByRole('combobox', { name: 'Platform' })).not.toBeInTheDocument();
  });
  it('keeps unknown counts empty and uses typed, labeled repeatable contacts', async () => {
    render(<Harness context={{ kind: 'creator', base: null }}/>); const user = userEvent.setup();
    await user.click(screen.getByText('Audience', { selector: 'summary' }));
    expect(screen.getByLabelText('Followers')).toHaveValue(null); await user.type(screen.getByLabelText('Followers'), '0');
    expect(screen.getByTestId('payload')).toHaveTextContent('"follower_count":0');
    await user.click(screen.getByText('Other contacts', { selector: 'summary' })); await user.click(screen.getByRole('button', { name: 'Add contact' }));
    await user.type(screen.getByLabelText('Contact value'), 'discord-harbor');
    expect(screen.getByTestId('payload')).toHaveTextContent('"other_contacts":[{"label":null,"value":"discord-harbor","url":null}]');
  });
  it('shows source comparison and emits reset without a conflicting field', async () => {
    render(<Harness context={{ kind: 'creator', base: creatorFormFixture() }}/>); const user = userEvent.setup();
    await user.click(screen.getByText('Source comparison', { selector: 'summary' })); await user.click(screen.getByRole('button', { name: 'Use source Name' }));
    expect(screen.getByLabelText('Name')).toHaveValue('Source Harbor');
    expect(screen.getByTestId('payload').textContent).toBe('{"expected_revision":7,"reset_fields":["name"]}');
  });
  it('never offers a verified toggle or permits resetting email with no source value', async () => {
    render(<Harness context={{ kind: 'contact', base: contactFormFixture(), creator: creatorFormFixture() }}/>); const user = userEvent.setup();
    await user.click(screen.getByText('Source comparison', { selector: 'summary' }));
    expect(screen.getByRole('button', { name: 'Use source Email' })).toBeDisabled();
    expect(screen.queryByRole('checkbox', { name: /verified/i })).not.toBeInTheDocument();
    await user.clear(screen.getByLabelText('Email')); expect(screen.getByTestId('payload')).toHaveTextContent('"email":null');
  });
  it('edits metric rows and resolves selected game labels while preserving selection on list failure', async () => {
    const api = games(); render(<Harness api={api} context={{ kind: 'work', base: workFormFixture({ game_id: '33333333-3333-4333-8333-333333333333' }), creator: creatorFormFixture() }}/>); const user = userEvent.setup();
    await user.click(screen.getByText('Metrics and game', { selector: 'summary' }));
    await screen.findByText('Existing game');
    await user.clear(screen.getByLabelText('Metric value')); await user.type(screen.getByLabelText('Metric value'), '0');
    expect(screen.getByTestId('payload')).toHaveTextContent('"value":0');
    expect(api.games.list).toHaveBeenCalledWith({ query: '', limit: 20, offset: 0 });
    vi.mocked(api.games.list).mockResolvedValueOnce({ ok: false, error: { code: 'network_error', message: 'Offline', retryable: true } });
    await user.click(screen.getByRole('button', { name: 'Next games' }));
    expect(await screen.findByText('Offline')).toBeVisible(); expect(screen.getByText('Existing game')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'No linked game' }));
    await waitFor(() => expect(screen.getByTestId('payload')).toHaveTextContent('"game_id":null'));
  });
  it('exposes every supported field through labeled controls or repeatable groups', async () => {
    const user = userEvent.setup(); const api = games();
    for (const kind of ['creator', 'contact', 'work'] as const) {
      const view = render(<Harness api={api} context={{ kind, base: null, creator: creatorFormFixture() }}/>);
      for (const summary of view.container.querySelectorAll('summary')) await user.click(summary);
      const fields = kind === 'creator' ? CREATOR_FIELDS : kind === 'contact' ? CONTACT_FIELDS : WORK_FIELDS;
      for (const key of fields) {
        const element = view.container.querySelector(`#creator-field-${key}`);
        expect(element, `${kind}.${key} is reachable`).not.toBeNull();
        if (!['metrics', 'other_contacts', 'languages'].includes(key)) expect(element).toHaveAccessibleName(key === 'game_id' ? 'Search games' : fieldLabel(key));
      }
      view.unmount();
    }
  });
  it('drops older game search results after a newer search completes', async () => {
    const api = games(); let finish!: (result: Awaited<ReturnType<DesktopBridge['games']['list']>>) => void;
    const older = new Promise<Awaited<ReturnType<DesktopBridge['games']['list']>>>(resolve => { finish = resolve; });
    vi.mocked(api.games.list).mockImplementation(async input => input.query === 'old' ? older : { ok: true, data: { items: [gameFixture(input.query || 'Initial')], limit: 20, offset: 0, total: 1 } });
    render(<Harness api={api} context={{ kind: 'work', base: null, creator: creatorFormFixture() }}/>); const user = userEvent.setup();
    await user.click(screen.getByText('Metrics and game', { selector: 'summary' })); const search = screen.getByRole('searchbox');
    await user.type(search, 'old{Enter}'); await user.clear(search); await user.type(search, 'new{Enter}');
    expect(await screen.findByRole('button', { name: 'Select game new' })).toBeVisible();
    await act(async () => finish({ ok: true, data: { items: [gameFixture('Stale')], limit: 20, offset: 0, total: 1 } }));
    expect(screen.queryByRole('button', { name: 'Select game Stale' })).not.toBeInTheDocument();
    expect(api.games.create).not.toHaveBeenCalled(); expect(api.games.update).not.toHaveBeenCalled();
  });
});
