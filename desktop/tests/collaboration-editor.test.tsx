// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { CollaborationEditor } from '../src/renderer/components/match/CollaborationEditor';
import type { ActivityInvitation } from '../src/shared/collaboration';
import { deliveryFixture } from './sending-fixtures';
afterEach(cleanup);

const row = (overrides: Partial<ActivityInvitation> = {}): ActivityInvitation => ({
  selection_id: 'selection-a', creator_id: 'creator-a', activity_id: 'activity-a', activity_name: 'Activity', selected: true,
  identity: { platform: 'youtube', account_id: 'channel-a' }, display_name: 'Creator A', revision: 2,
  sending_state: 'not_sent', invitation_state: 'not_invited', follow_up_state: 'not_followed_up', cooperation_state: 'not_started',
  notes: 'Saved notes', invited_at: null, responses: [], memberships: [], send_history: [], ...overrides,
});
const props = () => ({ invitation: row(), current: true, busy: false, onUpdate: vi.fn().mockResolvedValue(true), onRespond: vi.fn().mockResolvedValue(true), onDirtyChange: vi.fn() });
const click = (name: string) => fireEvent.click(screen.getByRole('button', { name }));

describe('CollaborationEditor', () => {
  it('opens response explicitly and requires chosen outcome, source and actual local time', async () => {
    const p = props(); render(<CollaborationEditor {...p}/>);
    expect(screen.queryByLabelText('Response')).not.toBeInTheDocument(); expect(p.onRespond).not.toHaveBeenCalled();
    click('Record response');
    expect(screen.getByLabelText('Response')).toHaveValue(''); expect(screen.getByLabelText(/Responded at/)).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Save response' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Response'), { target: { value: 'accepted' } });
    fireEvent.change(screen.getByLabelText('Source note'), { target: { value: 'Direct call confirmed acceptance' } });
    expect(screen.getByRole('button', { name: 'Save response' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Responded at/), { target: { value: '2026-09-08T10:30' } });
    click('Save response');
    await waitFor(() => expect(p.onRespond).toHaveBeenCalledWith({ expected_revision: 2, outcome: 'accepted', source_note: 'Direct call confirmed acceptance', responded_at: new Date(2026, 8, 8, 10, 30).toISOString() }));
    expect(p.onUpdate).not.toHaveBeenCalled();
  });
  it('submits only changed progress fields and sends empty notes to clear them', async () => {
    const p = props(); render(<CollaborationEditor {...p}/>); click('Edit progress');
    expect(screen.getByRole('button', { name: 'Save progress' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: '' } }); click('Save progress');
    await waitFor(() => expect(p.onUpdate).toHaveBeenCalledWith({ expected_revision: 2, notes: '' }));
    expect(p.onRespond).not.toHaveBeenCalled();
  });
  it('retains edits across relationships and stale readback until explicit rebinding', async () => {
    const p = props(); p.onUpdate.mockResolvedValue(false); const view = render(<CollaborationEditor {...p}/>); click('Edit progress');
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'Retained' } });
    view.rerender(<CollaborationEditor {...p} invitation={row({ selection_id: 'selection-b', display_name: 'Creator B' })}/>);
    expect(screen.queryByLabelText('Notes')).not.toBeInTheDocument();
    expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
    view.rerender(<CollaborationEditor {...p} invitation={row({ revision: 3, notes: 'Other operator' })}/>);
    expect(screen.getByLabelText('Notes')).toHaveValue('Retained'); expect(screen.getByRole('button', { name: 'Save progress' })).toBeDisabled();
    click('Use current version'); click('Save progress');
    await waitFor(() => expect(p.onUpdate).toHaveBeenCalledWith({ expected_revision: 3, notes: 'Retained' }));
    expect(screen.getByLabelText('Notes')).toHaveValue('Retained');
  });
  it('gates edits on current, busy and read-only without losing a response draft', () => {
    const p = props(); const view = render(<CollaborationEditor {...p}/>); click('Record response');
    fireEvent.change(screen.getByLabelText('Source note'), { target: { value: 'Unfinished verification' } });
    view.rerender(<CollaborationEditor {...p} current={false}/>); expect(screen.getByLabelText('Source note')).toHaveValue('Unfinished verification'); expect(screen.getByLabelText('Source note')).toBeDisabled();
    view.rerender(<CollaborationEditor {...p} editable={false}/>); expect(screen.queryByLabelText('Source note')).not.toBeInTheDocument(); expect(screen.queryByRole('button', { name: 'Record response' })).not.toBeInTheDocument();
    view.rerender(<CollaborationEditor {...p}/>); expect(screen.getByLabelText('Source note')).toHaveValue('Unfinished verification');
  });
  it('rebinding preserves intentional changes without overwriting untouched current progress', async () => {
    const p = props(); const view = render(<CollaborationEditor {...p}/>); click('Edit progress');
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'My note' } });
    view.rerender(<CollaborationEditor {...p} invitation={row({ revision: 3, cooperation_state: 'in_production', follow_up_state: 'followed_up' })}/>);
    click('Use current version'); click('Save progress');
    await waitFor(() => expect(p.onUpdate).toHaveBeenCalledWith({ expected_revision: 3, notes: 'My note' }));
  });
  it('clears only the successfully submitted relationship and retains other edits', async () => {
    const p = props(); let complete!: (value: boolean) => void; p.onUpdate.mockImplementation(() => new Promise(resolve => { complete = resolve; }));
    const view = render(<CollaborationEditor {...p}/>); click('Edit progress');
    fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'B draft' } });
    const b = row({ selection_id: 'selection-b' }); view.rerender(<CollaborationEditor {...p} invitation={b}/>); click('Record response');
    fireEvent.change(screen.getByLabelText('Source note'), { target: { value: 'Other retained source' } });
    view.rerender(<CollaborationEditor {...p}/>); click('Save progress');
    view.rerender(<CollaborationEditor {...p} invitation={b}/>); complete(true);
    await waitFor(() => expect(screen.getByLabelText('Source note')).toBeEnabled());
    expect(screen.getByLabelText('Source note')).toHaveValue('Other retained source'); expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
    view.rerender(<CollaborationEditor {...p}/>); expect(screen.queryByLabelText('Notes')).not.toBeInTheDocument();
  });
  it('rejects blank or oversized evidence and notes without calling a write', () => {
    const p = props(); render(<CollaborationEditor {...p}/>); click('Record response');
    fireEvent.change(screen.getByLabelText('Response'), { target: { value: 'declined' } });
    fireEvent.change(screen.getByLabelText(/Responded at/), { target: { value: '2026-09-08T10:30' } });
    for (const value of ['   ', 'x'.repeat(2001)]) { fireEvent.change(screen.getByLabelText('Source note'), { target: { value } }); expect(screen.getByRole('button', { name: 'Save response' })).toBeDisabled(); }
    click('Cancel'); click('Edit progress'); fireEvent.change(screen.getByLabelText('Notes'), { target: { value: 'x'.repeat(10001) } });
    expect(screen.getByRole('button', { name: 'Save progress' })).toBeDisabled(); expect(p.onUpdate).not.toHaveBeenCalled(); expect(p.onRespond).not.toHaveBeenCalled();
  });
  it('shows source history in revision order and loads only explicitly opened frozen mail', async () => {
    const p = props(); const delivery = deliveryFixture({ state: 'sent' });
    p.invitation = row({ responses: [
      { id: 'old', revision: 1, outcome: 'declined', source_note: 'Earlier source', responded_at: '2026-01-01T10:00:00Z', recorded_at: '2026-02-01T10:00:00Z' },
      { id: 'new', revision: 2, outcome: 'accepted', source_note: 'Later source', responded_at: '2026-01-02T10:00:00Z', recorded_at: '2026-02-02T10:00:00Z' },
    ], send_history: [{ send_batch_id: 'batch', composition_id: 'comp', draft_id: delivery.draft_id, recipient_snapshot_id: delivery.recipient_snapshot_id, created_at: '2026-01-01T10:00:00Z', qualification_status: 'eligible', exclusion_reason: null, delivery }] });
    render(<CollaborationEditor {...p}/>);
    expect(screen.queryByTitle('Frozen sent email')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Sending history')); click('View email 1');
    expect((await screen.findByTitle('Frozen sent email')).getAttribute('srcdoc')).toContain(delivery.snapshot.html);
    expect(screen.getByText(/SMTP accepted/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Response sources and history'));
    const notes = screen.getAllByTestId('response-source'); expect(notes.map(x => x.textContent)).toEqual(['Later source', 'Earlier source']);
    expect(screen.getAllByText(/Recorded at/)).toHaveLength(2); expect(screen.getAllByText(/Responded at/)).toHaveLength(2);
  });
  it('keeps the chosen frozen email when newer history arrives', async () => {
    const p = props(); const delivery = deliveryFixture();
    const old = { send_batch_id: 'old-batch', composition_id: 'old-comp', draft_id: delivery.draft_id, recipient_snapshot_id: delivery.recipient_snapshot_id, created_at: '2026-01-01T10:00:00Z', qualification_status: 'eligible' as const, exclusion_reason: null, delivery };
    p.invitation = row({ send_history: [old] }); const view = render(<CollaborationEditor {...p}/>);
    fireEvent.click(screen.getByText('Sending history')); click('View email 1'); await screen.findByTitle('Frozen sent email');
    const newer = { ...old, send_batch_id: 'new-batch', delivery: deliveryFixture({ id: 'new-delivery', snapshot: { ...delivery.snapshot, html: '<p>Newer unrelated frozen email</p>' } }) };
    view.rerender(<CollaborationEditor {...p} invitation={row({ send_history: [newer, old] })}/>);
    expect(screen.getByTitle('Frozen sent email').getAttribute('srcdoc')).toContain(delivery.snapshot.html);
    expect(screen.getByTitle('Frozen sent email').getAttribute('srcdoc')).not.toContain('Newer unrelated frozen email');
  });
});
