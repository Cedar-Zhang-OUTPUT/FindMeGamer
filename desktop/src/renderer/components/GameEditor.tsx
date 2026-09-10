import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { DesktopBridge, PublicError } from '../../shared/bridge';
import type { CreateGameInput, GameDetail, GamePage, NavigationGuard } from '../../shared/games';
import { GameForm } from './GameForm';
import { changeLabel, changedKeys, comparisonValue, createData, draftFrom, IDEMPOTENCY_WINDOW_MS, isDirty, localChangeValue, newRequestKey, patchData, resolveDraft, validateDraft, type ConflictChoices, type GameDraft } from './gameDraft';
import { ErrorNotice, Icon, Loading } from './Primitives';

type SaveState = 'editing' | 'saving' | 'uncertain' | 'created' | 'conflict';
interface Attempt { request: CreateGameInput; firstAttemptAt: number; workspaceChanged: boolean; credentialsChanged: boolean }
interface Conflict { latest: GameDetail | null; error: PublicError | null; choices: ConflictChoices }
const networkFailure: PublicError = { code: 'network_error', message: 'The connection was interrupted. Your changes are still here.', retryable: true };
const certainlyRejected = new Set(['request_invalid', 'workspace_key_invalid', 'game_identity_conflict', 'invalid_request', 'invalid_service_url', 'credentials_missing', 'secure_storage_unavailable', 'not_connected', 'access_denied', 'game_not_found', 'rate_limited']);
const authenticationFailures = new Set(['workspace_key_invalid', 'access_denied', 'not_connected', 'secure_storage_unavailable']);

function CreationMatches({page, busy, onPage, onSelect}: {page:GamePage; busy:boolean; onPage:(offset:number)=>void; onSelect:(id:string)=>void}) {
  return <div className="game-creation-lookup"><h4>Choose only if this is the game you created</h4>
    {page.items.length ? page.items.map(game => <div key={game.id}><strong>{game.name || game.website_url || game.id}</strong>{game.website_url && <span>{game.website_url}</span>}<code>{game.id}</code><button className="button secondary" disabled={busy} onClick={() => onSelect(game.id)}>Use this record</button></div>) : <p>No matching games. The creation result is still unresolved.</p>}
    {page.total > page.limit && <nav className="game-pagination" aria-label="Creation matches"><span>{page.offset + 1}–{page.offset + page.items.length} of {page.total}</span><span className="button-row"><button className="button secondary" disabled={busy || page.offset === 0} onClick={() => onPage(Math.max(0,page.offset-page.limit))}>Previous matches</button><button className="button secondary" disabled={busy || page.offset+page.limit >= page.total} onClick={() => onPage(page.offset+page.limit)}>Next matches</button></span></nav>}
  </div>;
}

function UnsavedDialog({ locked, busy, resolving, onStay, onDiscard, onSave }: { locked: boolean; busy: boolean; resolving: boolean; onStay: () => void; onDiscard: () => void; onSave: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; panel.current?.querySelector<HTMLButtonElement>('button')?.focus(); return () => previous?.focus(); }, []);
  return createPortal(<div className="modal-backdrop"><div ref={panel} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="game-unsaved-title" onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); onStay(); }
    if (event.key === 'Tab') { const buttons = panel.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'); if (!buttons?.length) return; const first = buttons[0], last = buttons[buttons.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
  }}><h2 id="game-unsaved-title">Unsaved game changes</h2><p>{locked ? 'The creation result is unknown. Resolve this request before starting another game.' : busy ? 'Your save is still in progress.' : resolving ? 'Resolve the conflicting values to save, or discard your local changes.' : 'Save your changes before leaving?'}</p><div className="game-dialog-actions"><button className="button secondary" onClick={onStay}>Continue editing</button><button className="text-button game-discard" disabled={locked || busy} onClick={onDiscard}>Discard changes</button><button className="button primary" disabled={locked || busy || resolving} onClick={onSave}>Save and leave</button></div></div></div>, document.body);
}

export function GameEditor({ api, initial, continuationLabel, headerAccessory, referenceSelection, onSaved, onCancel, onNavigationGuardChange, onConnectionRepair }: {
  api: DesktopBridge; initial: GameDetail | null; onSaved: (game: GameDetail, selectedReferences?:string[], intent?:'continue'|'leave') => void; onCancel: () => void;
  continuationLabel?: string;
  headerAccessory?: React.ReactNode;
  referenceSelection?: {ids:string[];onChange:(ids:string[])=>void};
  onNavigationGuardChange?: (guard: NavigationGuard | null) => void;
  onConnectionRepair?: () => void;
}) {
  const [base, setBase] = useState(initial);
  const [draft, setDraft] = useState<GameDraft>(() => draftFrom(initial));
  const [state, setState] = useState<SaveState>('editing');
  const [error, setError] = useState<PublicError | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [conflict, setConflict] = useState<Conflict | null>(null);
  const [pendingNavigation, setPendingNavigation] = useState<(() => void) | null>(null);
  const [lookup, setLookup] = useState<{ phase: 'loading' | 'ready'; page?: GamePage; error?: PublicError } | null>(null);
  const [recoveryAvailable, setRecoveryAvailable] = useState(false);
  const [, tick] = useState(0);
  const alive = useRef(true);
  const inFlight = useRef(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const latestNavigation = useRef<(() => void) | null>(null);
  const dirty = isDirty(base, draft);
  const locked = state === 'uncertain';
  const busy = state === 'saving';
  const needsGuard = state !== 'created' && (dirty || busy || locked || state === 'conflict');
  const credentialsChanged = useCallback(() => {
    // Workspace-key rotation changes the backend idempotency namespace. Retain the
    // original attempt but prohibit every subsequent POST, even at the same origin.
    setAttempt(previous => previous ? { ...previous, credentialsChanged: true } : previous);
    setError(null); setLookup(null); setPendingNavigation(null);
    // Keep recovery discoverable if the replacement key also needs correction.
    setRecoveryAvailable(true);
  }, []);
  const guard = useMemo<NavigationGuard>(() => {
    const handler: NavigationGuard = proceed => setPendingNavigation(() => proceed);
    if (recoveryAvailable) handler.recovery = { credentialsChanged };
    return handler;
  }, [recoveryAvailable, credentialsChanged]);
  useEffect(() => { alive.current = true; heading.current?.focus({ preventScroll: true }); return () => { alive.current = false; }; }, []);
  useEffect(() => { onNavigationGuardChange?.(needsGuard ? guard : null); return () => onNavigationGuardChange?.(null); }, [needsGuard, guard, onNavigationGuardChange]);
  useEffect(() => {
    if (!attempt || state !== 'uncertain') return;
    const remaining = Math.max(0, attempt.firstAttemptAt + IDEMPOTENCY_WINDOW_MS - Date.now());
    const timer = setTimeout(() => tick(value => value + 1), Math.min(remaining + 1, 2_147_483_647));
    return () => clearTimeout(timer);
  }, [attempt, state]);
  const expired = Boolean(attempt && Date.now() - attempt.firstAttemptAt >= IDEMPOTENCY_WINDOW_MS);

  function finish(game: GameDetail) {
    const proceed = latestNavigation.current;
    latestNavigation.current = null;
    onNavigationGuardChange?.(null);
    onSaved(game,selectedReferences(game),proceed?'leave':'continue');
    proceed?.();
  }
  function selectedReferences(saved:GameDetail){
    if(!referenceSelection)return undefined;
    const selected=draft.references.filter(reference=>referenceSelection.ids.includes(reference.id||reference.localId));
    const used=new Set<string>();
    for(const item of selected){
      const match=saved.reference_works.find(reference=>reference.id&&!used.has(reference.id)&&(item.id?item.id===reference.id:
        (item.name.trim()||null)===(reference.name??null)&&(item.url.trim()||null)===(reference.url??null)&&
        (item.reason.trim()||null)===(reference.reason??null)&&JSON.stringify(item.similarities.split('\n').map(value=>value.trim()).filter(Boolean))===JSON.stringify(reference.similarities)));
      if(match?.id)used.add(match.id);
    }
    return [...used];
  }
  async function readCreated(id: string) {
    if (inFlight.current) return;
    inFlight.current = true; setState('created'); setCreatedId(id); setError(null);
    try {
      const response = await api.games.detail(id);
      if (!alive.current) return;
      if (response.ok) finish(response.data); else { setError(response.error); latestNavigation.current = null; }
    } catch { if (alive.current) { setError(networkFailure); latestNavigation.current = null; } }
    finally { inFlight.current = false; if (alive.current) tick(value => value + 1); }
  }
  async function loadConflict() {
    if (!base) return;
    setConflict({ latest: null, error: null, choices: {} });
    try {
      const response = await api.games.detail(base.id);
      if (!alive.current) return;
      setConflict({ latest: response.ok ? response.data : null, error: response.ok ? null : response.error, choices: {} });
    } catch { if (alive.current) setConflict({ latest: null, error: networkFailure, choices: {} }); }
  }
  async function save(retryAttempt = false, proceed?: () => void) {
    if (inFlight.current || state === 'conflict' || state === 'created' || (state === 'uncertain' && !retryAttempt)) return;
    if (retryAttempt && (!attempt || Date.now() - attempt.firstAttemptAt >= IDEMPOTENCY_WINDOW_MS || attempt.workspaceChanged || attempt.credentialsChanged)) { tick(value => value + 1); return; }
    const errors = validateDraft(draft, base);
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      setPendingNavigation(null);
      requestAnimationFrame(() => { const element = document.getElementById(`game-${Object.keys(errors)[0]}`); const disclosure = element?.closest('details'); if (disclosure) disclosure.open = true; element?.focus(); });
      return;
    }
    if (base && !dirty) { if (proceed) proceed(); else if (continuationLabel) onSaved(base,selectedReferences(base)); else onCancel(); return; }
    setPendingNavigation(null); latestNavigation.current = proceed ?? null;
    inFlight.current = true; setState('saving'); setError(null);
    try {
      if (base) {
        const response = await api.games.update({ id: base.id, data: patchData(base, draft) });
        if (!alive.current) return;
        if (response.ok) finish(response.data);
        else if (response.error.code === 'game_revision_conflict') { setState('conflict'); setError(null); latestNavigation.current = null; void loadConflict(); }
        else { setState('editing'); setError(response.error); if (authenticationFailures.has(response.error.code)) setRecoveryAvailable(true); latestNavigation.current = null; }
      } else {
        const frozen = retryAttempt && attempt ? attempt : { request: { data: createData(draft), idempotencyKey: newRequestKey() }, firstAttemptAt: Date.now(), workspaceChanged: false, credentialsChanged: false };
        setAttempt(frozen);
        const response = await api.games.create(frozen.request);
        if (!alive.current) return;
        if (response.ok) {
          inFlight.current = false;
          await readCreated(response.data.id);
        } else {
          // A rejected replay cannot prove that the original uncertain request did not commit.
          const rejected = !retryAttempt && certainlyRejected.has(response.error.code);
          setState(rejected ? 'editing' : 'uncertain'); setError(response.error);
          if (authenticationFailures.has(response.error.code)) setRecoveryAvailable(true);
          if (rejected) setAttempt(null);
          else if (response.error.code === 'connection_changed') setAttempt(previous => {
            // A verified same-origin key repair can race a pending response. It
            // still forbids replay, but read-only verification remains permitted.
            if (previous?.request.idempotencyKey === frozen.request.idempotencyKey) return previous.credentialsChanged ? previous : { ...previous, workspaceChanged: true };
            return { ...frozen, workspaceChanged: true };
          });
          latestNavigation.current = null;
        }
      }
    } catch { if (alive.current) { setState(base ? 'editing' : 'uncertain'); setError(networkFailure); latestNavigation.current = null; } }
    finally { inFlight.current = false; }
  }
  async function checkLibrary(offset = 0) {
    if (!attempt || attempt.workspaceChanged || lookup?.phase === 'loading') return;
    setLookup(previous => ({ ...previous, phase: 'loading', error: undefined }));
    try {
      // Match the server's canonical public URL (IDN and path escaping included).
      const identity = attempt.request.data.name || (attempt.request.data.website_url ? new URL(attempt.request.data.website_url).href : '');
      const query = Array.from(identity).slice(0,255).join('');
      const response = await api.games.list({ query, limit: 24, offset });
      if (!alive.current) return;
      if (!response.ok && authenticationFailures.has(response.error.code)) setRecoveryAvailable(true);
      setLookup(response.ok ? { phase: 'ready', page: response.data } : { phase: 'ready', error: response.error });
    } catch { if (alive.current) setLookup({ phase: 'ready', error: networkFailure }); }
  }
  function back() { if (needsGuard) guard(onCancel); else onCancel(); }

  if (state === 'created') return <section className="game-created-state"><h2 ref={heading} tabIndex={-1}>Game created</h2><code>{createdId}</code>{error ? <><ErrorNotice error={error}/><button className="button primary" onClick={() => createdId && void readCreated(createdId)}>Retry latest</button><button className="text-button" onClick={onCancel}>Back to games</button></> : <Loading label="Loading latest game…"/>}</section>;
  return <div className="game-editor"><div className="game-editor-heading"><button className="text-button" onClick={back}><Icon name="arrow"/>Back to games</button>{(busy || dirty) && <span className="read-only-label">{busy ? 'Saving…' : 'Unsaved changes'}</span>}</div><h2 ref={heading} tabIndex={-1}>{continuationLabel?'Game details & references':base ? 'Edit game' : 'New game'}</h2>{headerAccessory}
    {state === 'conflict' && base ? <section className="game-conflict" aria-label="Conflict resolution"><h3>Resolve changes</h3><p>Another editor saved this game.</p>{conflict?.error ? <ErrorNotice error={conflict.error} onRetry={() => void loadConflict()}/> : !conflict?.latest ? <Loading label="Loading latest record…"/> : <>
      <div className="game-conflict-rows">{changedKeys(base, draft).map(key => {
        const usesSource = key !== 'favorite' && key !== 'reference_works' && draft.resets.includes(key);
        const valueToApply = usesSource ? conflict.latest!.source_fields[key] : localChangeValue(draft, key);
        return <fieldset key={key}><legend>{changeLabel(key)}</legend><label><input type="radio" name={`resolve-${key}`} aria-label={`Use latest: ${changeLabel(key)}`} checked={conflict.choices[key] === 'latest'} onChange={() => setConflict({ ...conflict, choices: { ...conflict.choices, [key]: 'latest' } })}/><span><strong>Use latest</strong><pre>{comparisonValue(conflict.latest![key])}</pre></span></label><label><input type="radio" name={`resolve-${key}`} aria-label={`Keep mine: ${changeLabel(key)}`} checked={conflict.choices[key] === 'mine'} onChange={() => setConflict({ ...conflict, choices: { ...conflict.choices, [key]: 'mine' } })}/><span><strong>{usesSource ? 'Use current source' : 'Keep mine'}</strong><pre>{comparisonValue(valueToApply)}</pre></span></label></fieldset>;
      })}</div>
      <details className="game-latest-record"><summary>Latest record · Revision {conflict.latest.revision}</summary><pre>{JSON.stringify(conflict.latest, null, 2)}</pre></details>
      <button className="button primary" disabled={changedKeys(base, draft).some(key => !conflict.choices[key])} onClick={() => { const latest = conflict.latest!; setDraft(resolveDraft(base, draft, latest, conflict.choices)); setBase(latest); setConflict(null); setState('editing'); setError(null); }}>Apply choices</button>
    </>}</section> : <>
      {locked && <section className="game-uncertain" aria-label="Unconfirmed creation"><h3>Creation result unknown</h3><p>{attempt?.workspaceChanged ? 'The workspace changed. This request cannot be replayed into another workspace. Return to the original workspace to verify its result.' : attempt?.credentialsChanged ? 'Credentials changed. Check the original Library to confirm the saved game.' : expired ? 'The 24-hour safe retry window has ended. Check Library before deciding which record to use.' : 'The game may already be saved. Retry safely or check Library.'}</p><div className="button-row"><button className="button primary" disabled={expired || attempt?.workspaceChanged || attempt?.credentialsChanged} onClick={() => void save(true)}>Retry creation</button><button className="button secondary" disabled={attempt?.workspaceChanged || lookup?.phase === 'loading'} onClick={() => void checkLibrary()}>Check Library</button></div>{lookup?.phase === 'loading' && <Loading label="Checking Library…"/>}{lookup?.error && <ErrorNotice error={lookup.error}/>} {lookup?.page && <CreationMatches page={lookup.page} busy={lookup.phase === 'loading'} onPage={offset => void checkLibrary(offset)} onSelect={id => void readCreated(id)}/>}</section>}
      {error && <ErrorNotice error={error}/>}
      {recoveryAvailable && onConnectionRepair && <button className="button secondary" type="button" onClick={onConnectionRepair}>Repair connection</button>}
      {Object.keys(fieldErrors).length > 0 && <div className="game-validation-summary" role="alert">Check the highlighted fields.</div>}
      <form noValidate onSubmit={event => { event.preventDefault(); void save(); }}><GameForm api={api} base={base} draft={draft} disabled={busy || locked} errors={fieldErrors} selection={referenceSelection} onChange={next => { setDraft(next); setFieldErrors({}); setError(null); }}/><div className="game-editor-footer"><button className="button secondary" type="button" disabled={busy || locked} onClick={back}>Cancel</button><button className="button primary" type="submit" disabled={busy || locked || (Boolean(base) && !dirty && !continuationLabel)}>{busy ? 'Saving…' : continuationLabel ?? (base ? 'Save changes' : 'Create game')}</button></div></form>
    </>}
    {pendingNavigation && <UnsavedDialog locked={locked} busy={busy} resolving={state === 'conflict'} onStay={() => setPendingNavigation(null)} onDiscard={() => { const proceed = pendingNavigation; setPendingNavigation(null); setDraft(draftFrom(base)); onNavigationGuardChange?.(null); if (proceed !== onCancel) onCancel(); proceed(); }} onSave={() => void save(false, pendingNavigation)}/>}
  </div>;
}
