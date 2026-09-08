import { useEffect, useRef, useState } from 'react';
import type { CompositionView, DraftView, FactMember, SenderFacts } from '../../../shared/drafts';
import './senderFactsEditor.css';

export interface SenderFactsEditorProps {
  composition: CompositionView; busy: boolean; current: boolean;
  onSave(data: SenderFacts): Promise<boolean>; onDirtyChange?(dirty: boolean): void;
}
const emptyFacts = { following: false, enjoyed: false, liked: false };
const attestations = { following: 'I follow these channels', enjoyed: 'I enjoyed the referenced work', liked: 'I liked the described details' } as const;
const completed = (d: DraftView) => d.status === 'succeeded' && d.values !== null && d.rendered !== null && !d.source_changed;
const member = (d: DraftView): FactMember => ({ draft_id: d.id, expected_revision: d.revision, context_token: d.context_token });
const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export function SenderFactsEditor({ composition, busy, current, onSave, onDirtyChange }: SenderFactsEditorProps) {
  const [chosen, setChosen] = useState<FactMember[]>([]);
  const [facts, setFacts] = useState(emptyFacts);
  const [scope, setScope] = useState(composition.id);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const inflight = useRef(false);
  const eligible = composition.drafts.filter(completed).slice(0, 600);
  const stale = chosen.length > 0 && (!same(scope, composition.id) || chosen.some(m => {
    const d = composition.drafts.find(d => same(d.id, m.draft_id));
    return !d || !completed(d) || d.revision !== m.expected_revision || d.context_token !== m.context_token;
  }));
  const dirty = chosen.length > 0 || Object.values(facts).some(Boolean);
  const disabled = busy || saving || !current;
  useEffect(() => { onDirtyChange?.(dirty); }, [dirty, onDirtyChange]);
  function clear() { setChosen([]); setFacts(emptyFacts); setScope(composition.id); setError(''); }
  function toggle(d: DraftView, checked: boolean) {
    if (disabled || stale) return;
    setScope(composition.id);
    setChosen(old => checked ? [...old.filter(m => !same(m.draft_id, d.id)), member(d)].slice(0, 600) : old.filter(m => !same(m.draft_id, d.id)));
    setError('');
  }
  async function save() {
    if (disabled || stale || !chosen.length || inflight.current) return;
    const data: SenderFacts = { members: chosen.map(m => ({ ...m })), ...facts };
    inflight.current = true; setSaving(true); setError('');
    try { if (await onSave(data)) clear(); else setError('Confirmations were not accepted. Your choices are kept.'); }
    catch { setError('The confirmation result could not be verified. Your choices are kept.'); }
    finally { inflight.current = false; setSaving(false); }
  }
  return <details className="sender-facts-editor">
    <summary>Sender confirmations</summary>
    <div className="sender-facts-content">
      <p>Choose completed people, then record your own experience. Unchecked statements are saved as false.</p>
      {stale && <div role="alert"><p>These drafts changed since you selected them. Reloading clears your selected people and all three confirmations.</p><button type="button" disabled={disabled} onClick={clear}>Reload choices and clear confirmations</button></div>}
      <fieldset disabled={disabled || stale}>
        <legend>Completed people ({eligible.length})</legend>
        <div className="sender-facts-actions"><button type="button" disabled={!eligible.length} onClick={() => { setScope(composition.id); setChosen(eligible.map(member)); setError(''); }}>Select completed</button><button type="button" onClick={clear}>Clear</button></div>
        <ul className="sender-facts-members">{composition.drafts.map((d, i) => <li key={d.id}><label><input type="checkbox" disabled={!completed(d)} checked={chosen.some(m => same(m.draft_id, d.id))} onChange={e => toggle(d, e.target.checked)} /><span>{typeof d.input.channel_name === 'string' && d.input.channel_name ? d.input.channel_name : `Person ${i + 1}`}{!completed(d) && <small> — {d.source_changed ? 'sources changed' : 'not completed'}</small>}</span></label></li>)}</ul>
      </fieldset>
      <fieldset disabled={disabled || stale}><legend>Your confirmations</legend>{(Object.keys(attestations) as (keyof typeof attestations)[]).map(key => <label key={key}><input type="checkbox" checked={facts[key]} onChange={e => { setFacts(old => ({ ...old, [key]: e.target.checked })); setError(''); }} /><span>{attestations[key]}</span></label>)}</fieldset>
      {error && <p role="alert">{error}</p>}
      <button type="button" disabled={disabled || stale || !chosen.length} onClick={() => void save()}>Save confirmations for {chosen.length}</button>
      {saving && <span role="status">Saving confirmations…</span>}
    </div>
  </details>;
}
