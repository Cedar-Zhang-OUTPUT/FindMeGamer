import { useEffect, useId, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { CompositionPage, DraftsAPI, DraftView } from '../../../shared/drafts';
import type { useActivityDrafts } from './useActivityDrafts';
import { TemplatePicker } from './TemplatePicker';
import { DraftEditor } from './DraftEditor';
import { SenderFactsEditor } from './SenderFactsEditor';
import { useDraftTemplatePreview } from './useDraftTemplatePreview';
import { PreparationSnapshot } from './PreparationEditor';
import { ErrorNotice, Loading, analyzedDate } from '../Primitives';
import './draftsWorkspace.css';
export interface DraftsWorkspaceProps { api: DesktopBridge; controller: ReturnType<typeof useActivityDrafts>; active: boolean; onRequest(action: () => void): void; onBack(): void; onRepairPerson(selectionId: string, section: 'overview' | 'contacts' | 'works'): void; onConnectionRepair?(): void; onReviewSending?():void; sendingDisabled?:boolean;onUseCurrentTemplate?():void }
export interface CompositionHistoryProps { api: DraftsAPI; activityId: string; active: boolean; epoch: number; disabled: boolean; onOpen(id: string): void }
const labels: Record<DraftView['status'], string> = { pending: 'Queued', running: 'Generating', succeeded: 'Complete', failed: 'Failed', needs_repair: 'Needs repair' };
export function DraftsWorkspace({ api,controller: c, active, onRequest, onBack, onRepairPerson, onConnectionRepair, onReviewSending,onUseCurrentTemplate, sendingDisabled=false }: DraftsWorkspaceProps) {
  // Keep the form owner mounted while credential repair invalidates fetched data.
  // The retained game is display context only; writes stay disabled until reread.
  const retainedGame=useRef(c.game);if(c.game)retainedGame.current=c.game;
  const heading=useRef<HTMLHeadingElement>(null),focusedSet=useRef<string|null>(null);
  const visible = active && c.mode.kind !== 'people';
  const editing = visible && c.mode.kind === 'composition';
  const templateId=c.composition?.template_version_id??null;
  const preview=useDraftTemplatePreview(api.drafts,templateId,editing&&!!c.composition?.drafts.some(row=>!row.rendered),c.catalog?.items.find(item=>item.id===templateId));
  const selected = c.composition?.drafts.find(row => row.id === c.selectedId);
  const original = selected && c.batch?.recipients.find(row => row.id === selected.recipient_snapshot_id && row.selection_id === selected.selection_id);
  const busy = c.busy || c.locked || !visible;
  const operation = c.operation.state;
  const uncertain = operation.phase === 'uncertain';
  const credentialChanged = uncertain && operation.attempt.connectionChanged;
  const canCheck = uncertain && !credentialChanged && !['createTemplate', 'createComposition'].includes(operation.attempt.command.kind);
  const error = operation.error ?? c.error;
  const counts = c.composition?.drafts.reduce((totals, row) => ({ ...totals, [row.status]: (totals[row.status] ?? 0) + 1 }), {} as Partial<Record<DraftView['status'], number>>);
  useEffect(()=>{if(editing&&c.current&&c.composition&&focusedSet.current!==c.composition.id){focusedSet.current=c.composition.id;heading.current?.focus({preventScroll:true});}},[editing,c.current,c.composition?.id]);
  return <section className="drafts-workspace" hidden={!visible} aria-label="Outreach drafts">
    <header className="drafts-workspace-heading"><div><button className="text-button" type="button" disabled={c.operation.busy} onClick={() => onRequest(onBack)}>Back to people</button>
      {c.mode.kind!=='template'&&<h2 ref={heading} tabIndex={-1}>{c.composition?`${c.composition.recipient_count} drafts`:'Draft set'}</h2>}</div>
      {counts && c.mode.kind === 'composition' && <p className="drafts-status-counts">{Object.entries(counts).map(([status, count]) => `${count} ${labels[status as DraftView['status']].toLowerCase()}`).join(' · ')}</p>}
    </header>
    {c.notice && <p className="drafts-notice" role="status">{c.notice}</p>}
    {error && <ErrorNotice error={error} onRetry={!uncertain && !busy ? () => void c.refresh() : undefined} />}
    {c.loading && <Loading label="Loading drafts…" />}
    {uncertain && <div className="drafts-recovery" role="region" aria-label="Unconfirmed draft change">
      <p>{credentialChanged ? 'The connection changed. This operation still belongs to its original connection.' : 'This change may already be saved. Keep the original request while checking its result.'}</p>
      <div className="button-row">
        {c.operation.retryAllowed && <button type="button" className="button secondary" disabled={c.busy || !visible} onClick={() => void c.retry()}>Retry same request</button>}
        {canCheck && <button type="button" className="button secondary" disabled={c.busy || !visible} onClick={() => void c.check()}>Check current version</button>}
        {credentialChanged && onConnectionRepair && <button type="button" className="button secondary" disabled={c.busy || !visible} onClick={onConnectionRepair}>Review connection</button>}
      </div>
      {c.readback && !credentialChanged && <div className="drafts-readback"><p>The current version is available for review. Loading it does not confirm that the previous save succeeded.</p>
        <button type="button" className="button secondary" disabled={c.busy || !visible} onClick={c.reviewCurrent}>Review current version</button></div>}
    </div>}
    {retainedGame.current && <TemplatePicker key={`template:${c.editorEpoch}`} game={retainedGame.current} catalog={c.catalog} selectedId={c.selectedTemplate}
      active={visible && c.mode.kind === 'template'} busy={busy||!c.game||!c.catalog} recipientCount={c.batch?.recipient_count ?? 0}
      onSelect={c.selectTemplate} onRegister={c.register} onContinue={() => void c.create()}
      onRetry={() => void c.refresh()} onDirtyChange={value => c.setDirty('template', value)} />}
    {!c.game && c.mode.kind === 'template' && !c.loading && <button type="button" className="button secondary" disabled={busy} onClick={() => void c.refresh()}>Load templates</button>}
    {c.composition && <div className="drafts-composition" hidden={!editing}>
      <div className="drafts-composition-layout">
        <nav className="drafts-roster" aria-label="Draft people"><ol>{c.composition.drafts.map((row, index) => {
          const snapshot = c.batch?.recipients.find(person => person.id === row.recipient_snapshot_id && person.selection_id === row.selection_id)?.snapshot;
          const name = typeof row.input.channel_name === 'string' && row.input.channel_name ? row.input.channel_name : snapshot?.name || snapshot?.public_name || `Person ${index + 1}`;
          return <li key={row.id}><button type="button" aria-current={row.id === selected?.id ? 'true' : undefined} disabled={c.operation.busy || !editing}
            onClick={() => { if (row.id !== selected?.id) onRequest(() => c.setSelectedId(row.id)); }}>
            <span className="draft-roster-name">{name}</span><span className={`draft-roster-status status-${row.status}`}>{row.source_changed ? 'Sources changed' : labels[row.status]}</span>
          </button></li>;
        })}</ol></nav>
        <div className="drafts-selected-mail">
          {selected ? <><DraftEditor key={`editor:${c.editorEpoch}:${c.composition.id}`} draft={selected} busy={busy} current={editing && c.current}
            previewTemplate={preview.template} previewLoading={preview.loading} previewError={preview.error} onReloadPreview={preview.reload}
            onUseCurrentTemplate={onUseCurrentTemplate} onSave={c.saveDraft} onRefresh={() => c.regenerate('refresh')} onRetry={() => void c.regenerate('retry')}
            onOpenSource={section => onRepairPerson(selected.selection_id, section)} onDirtyChange={value => c.setDirty('editor', value)} />
            {original && <details className="drafts-original"><summary>Original recipient snapshot</summary><PreparationSnapshot preparation={original.snapshot} /></details>}
          </> : <p>Choose a person to inspect their draft.</p>}
        </div>
      </div>
      <SenderFactsEditor key={`facts:${c.editorEpoch}:${c.composition.id}`} composition={c.composition} busy={busy} current={editing && c.current}
        onSave={c.saveFacts} onDirtyChange={value => c.setDirty('facts', value)} />
      {onReviewSending&&<footer className="qualification-actions"><button type="button" className="button primary" disabled={busy||!c.current||c.dirty||sendingDisabled} onClick={onReviewSending}>Review sending</button></footer>}
    </div>}
  </section>;
}

const historyReadError: PublicError = { code: 'draft_history_read_failed', message: 'Could not load draft history. Try again.', retryable: true };
export function CompositionHistory({ api, activityId, active, epoch, disabled, onOpen }: CompositionHistoryProps) {
  const id = useId();
  const [expanded, setExpanded] = useState(false), [offset, setOffset] = useState(0), [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(false), [error, setError] = useState<PublicError | null>(null);
  const [record, setRecord] = useState<{ activityId: string; epoch: number; offset: number; page: CompositionPage } | null>(null);
  useEffect(() => { setOffset(0); }, [activityId, epoch]);
  useEffect(() => {
    let live = true;
    setRecord(null); setError(null);
    if (!expanded || !active || disabled) { setLoading(false); return; }
    setLoading(true);
    void api.compositions({ activityId, offset, limit: 50 }).then(result => {
      if (!live) return;
      if (!result.ok) { setError(result.error); return; }
      const page = result.data;
      if (page.offset !== offset || page.limit !== 50 || page.items.length > 50 || page.items.some(item => item.activity_id !== activityId)
        || new Set(page.items.map(item => item.id)).size !== page.items.length) { setError(historyReadError); return; }
      setRecord({ activityId, epoch, offset, page });
    }).catch(() => { if (live) setError(historyReadError); }).finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [api, activityId, active, epoch, disabled, expanded, offset, refresh]);
  const page = record?.activityId === activityId && record.epoch === epoch && record.offset === offset ? record.page : null;
  const available = active && !disabled && !loading && !!page;
  return <section className="drafts-history" aria-label="Draft history">
    <button type="button" className="drafts-history-toggle" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>Draft history</button>
    <div id={id} hidden={!expanded}>
      {loading && <Loading label="Loading draft history…" />}
      {error && <ErrorNotice error={error} onRetry={active && !disabled ? () => setRefresh(value => value + 1) : undefined} />}
      {page && <><ul>{page.items.map(item => <li key={item.id}><div><strong>{item.recipient_count} {item.recipient_count === 1 ? 'person' : 'people'}</strong><span>{analyzedDate(item.created_at)}</span></div>
        <button type="button" className="button secondary" disabled={!available} onClick={() => { if (available) {setExpanded(false);onOpen(item.id);} }}>Open draft set</button></li>)}</ul>
        {!page.items.length && <p className="muted">No draft sets on this page.</p>}
        <footer><span>{page.total} draft {page.total === 1 ? 'set' : 'sets'}</span><div className="button-row">
          <button type="button" disabled={!available || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>Previous draft sets</button>
          <button type="button" disabled={!available || offset + 50 >= page.total} onClick={() => setOffset(value => value + 50)}>Next draft sets</button>
        </div></footer></>}
    </div>
  </section>;
}
