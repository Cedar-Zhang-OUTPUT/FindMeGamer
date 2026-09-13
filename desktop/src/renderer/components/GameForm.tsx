import {ScopedSelectionActions} from './SelectionActions';
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { GAME_FIELDS, type GameDetail, type GameField } from '../../shared/games';
import { comparisonValue, displayField, gameLabels, newReference, validateDraft, type GameDraft, type ReferenceDraft } from './gameDraft';
import type { DesktopBridge } from '../../shared/bridge';
import { SteamReferenceSource, SteamRecommendationsStatus } from './SteamReferenceSource';

function AddReference({draft,onAdd,onCancel}:{draft:GameDraft;onAdd:(reference:ReferenceDraft)=>void;onCancel:()=>void}){
  const [reference,setReference]=useState(newReference),[errors,setErrors]=useState<Record<string,string>>({});
  const panel=useRef<HTMLFormElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;panel.current?.querySelector<HTMLInputElement>('input')?.focus();return()=>previous?.focus();},[]);
  const update=(key:'name'|'url'|'reason',value:string)=>setReference(previous=>({...previous,[key]:value}));
  return createPortal(<div className="modal-backdrop"><form ref={panel} className="confirm-dialog reference-dialog" role="dialog" aria-modal="true" aria-labelledby="add-reference-title" onSubmit={event=>{event.preventDefault();event.stopPropagation();const next=validateDraft({...draft,references:[reference]});const issues=Object.fromEntries(Object.entries(next).filter(([key])=>key.startsWith('reference-')));setErrors(issues);if(!Object.keys(issues).length)onAdd(reference);}} onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onCancel();}
    if(event.key==='Tab'){const controls=panel.current?.querySelectorAll<HTMLElement>('input,textarea,button');if(!controls?.length)return;const first=controls[0],last=controls[controls.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
  }}><h2 id="add-reference-title">Add reference</h2>{(['name','url'] as const).map(key=><div className="form-field" key={key}><label htmlFor={`new-reference-${key}`}>{key==='name'?'Reference name':'Reference URL'}</label><input id={`new-reference-${key}`} value={reference[key]} onChange={event=>update(key,event.target.value)} aria-invalid={Boolean(errors[`reference-${reference.localId}-${key}`])}/>{errors[`reference-${reference.localId}-${key}`]&&<span role="alert" className="game-field-error">{errors[`reference-${reference.localId}-${key}`]}</span>}</div>)}
    <fieldset className="reference-similarities"><legend>Similarities · Optional</legend>{['Gameplay','Theme','Narrative','Art style','Audience','Other'].map(value=><label key={value}><input type="checkbox" checked={reference.similarities.split('\n').includes(value)} onChange={event=>setReference(previous=>({...previous,similarities:(event.target.checked?[...previous.similarities.split('\n').filter(Boolean),value]:previous.similarities.split('\n').filter(item=>item!==value)).join('\n')}))}/>{value}</label>)}</fieldset>
    <div className="form-field"><label htmlFor="new-reference-reason">Reason · Optional</label><textarea id="new-reference-reason" value={reference.reason} onChange={event=>update('reason',event.target.value)} rows={2}/></div>{errors[`reference-${reference.localId}-reason`]&&<p role="alert">{errors[`reference-${reference.localId}-reason`]}</p>}
    <div className="game-dialog-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button className="button primary" type="submit">Add</button></div>
  </form></div>,document.body);
}

export function GameForm({ base, draft, disabled, errors, onChange, selection, api }: {
  base: GameDetail | null; draft: GameDraft; disabled: boolean; errors: Record<string, string>; onChange: (draft: GameDraft) => void;
  selection?: {ids:string[];onChange:(ids:string[])=>void};
  api?: Pick<DesktopBridge, 'openExternal'>;
}) {
  const [expandedReferences, setExpandedReferences] = useState<Set<string>>(new Set());
  const [adding,setAdding]=useState(false);
  function changeField(field: GameField, value: string) {
    onChange({ ...draft, fields: { ...draft.fields, [field]: value }, touched: [...new Set([...draft.touched, field])], resets: draft.resets.filter(item => item !== field) });
  }
  function field(field: GameField) {
    const multiline = ['description', 'tags', 'languages'].includes(field);
    const props = {
      id: `game-${field}`, value: draft.fields[field], 'aria-label': gameLabels[field], 'aria-description': draft.resets.includes(field) ? 'Will use source' : undefined, 'aria-invalid': Boolean(errors[field]),
      'aria-describedby': errors[field] ? `error-${field}` : undefined,
      onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => changeField(field, event.target.value),
    };
    return <div className={`form-field game-field ${field === 'description' ? 'game-description' : ''}`} key={field}>
      <label htmlFor={props.id}>{gameLabels[field]}{draft.resets.includes(field)?<span className="game-source-badge">Will use source</span>:base&&['description','tags'].includes(field)&&<span className="game-source-badge">{draft.touched.includes(field)||base.overridden_fields.includes(field)?'Manually edited':'Source facts'}</span>}</label>
      {multiline ? <textarea {...props} rows={field === 'description' ? 5 : 2} placeholder={field === 'tags' ? 'One tag per line' : field === 'languages' ? 'One language per line' : undefined}/> : <input {...props} type="text" spellCheck={!['website_url', 'cover_url', 'steam_app_id'].includes(field)} placeholder={field === 'release_date' ? 'e.g. September 2026 or Coming soon' : undefined}/>}
      {errors[field] && <span id={`error-${field}`} className="game-field-error">{errors[field]}</span>}
    </div>;
  }
  function updateReference(localId: string, changes: Partial<ReferenceDraft>) {
    onChange({ ...draft, referencesTouched: true, references: draft.references.map(reference => reference.localId === localId ? { ...reference, ...changes } : reference) });
  }
  function referenceField(reference: ReferenceDraft, key: 'name' | 'url' | 'similarities' | 'reason', label: string) {
    const errorKey = `reference-${reference.localId}-${key}`;
    const id = `game-${errorKey}`;
    const props = { id, value: reference[key], 'aria-invalid': Boolean(errors[errorKey]), 'aria-describedby': errors[errorKey] ? `error-${errorKey}` : undefined, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => updateReference(reference.localId, { [key]: event.target.value }) };
    return <div className="form-field" key={key}><label htmlFor={id}>{label}</label>{key === 'similarities' || key === 'reason' ? <textarea {...props} rows={2} placeholder={key === 'similarities' ? 'One similarity per line' : undefined}/> : <input {...props} type="text"/>}{errors[errorKey] && <span className="game-field-error" id={`error-${errorKey}`}>{errors[errorKey]}</span>}</div>;
  }
  return <fieldset className="game-form-fields" disabled={disabled}>
    <div className="game-editor-columns"><section className="game-primary-fields"><div className="game-fields-grid">{field('name')}{field('steam_app_id')}{field('website_url')}{field('developer')}{field('release_date')}</div>{field('description')}{field('tags')}
      <details className="game-additional"><summary>Languages, cover & more</summary><div className="game-fields-grid">{field('languages')}{field('cover_url')}</div>{base && <p className="game-binding-note">Website and Steam ID edits do not change the source binding.</p>}</details>
      <label className="game-favorite"><input type="checkbox" checked={draft.favorite} onChange={event => onChange({ ...draft, favorite: event.target.checked })}/>Saved</label>
    </section>
    <section className="game-references" aria-label="Reference works"><div className="game-section-title"><h3>Reference works <span className="count">{draft.references.length}</span></h3><button className="button secondary" type="button" disabled={draft.references.length >= 100} onClick={()=>setAdding(true)}>Add reference</button></div>
      <SteamRecommendationsStatus state={base?.steam_recommendations}/>
      {adding&&<AddReference draft={draft} onCancel={()=>setAdding(false)} onAdd={reference=>{const existing=draft.references.find(item=>reference.url.trim()?item.url.trim()===reference.url.trim():item.name.trim().toLocaleLowerCase()===reference.name.trim().toLocaleLowerCase());setAdding(false);if(existing){setExpandedReferences(previous=>new Set([...previous,existing.localId]));requestAnimationFrame(()=>document.getElementById(`game-reference-${existing.localId}-name`)?.focus());}else onChange({...draft,referencesTouched:true,references:[...draft.references,reference]});}}/>}
      {errors.references && <p className="game-field-error">{errors.references}</p>}
      {selection&&<ScopedSelectionActions scope="Listed reference works" ids={draft.references.map(reference=>reference.id||reference.localId)} selected={selection.ids} onChange={selection.onChange} disabled={disabled} limit={100}/>}
      {draft.references.map((reference, index) => {
        const label = reference.name.trim() || reference.url.trim() || `Reference ${index + 1}`;
        const hasError = Object.keys(errors).some(key => key.startsWith(`reference-${reference.localId}-`));
        const expanded = expandedReferences.has(reference.localId) || hasError;
        const selectionKey=reference.id||reference.localId;
        return <div className="game-reference-card" key={reference.localId}><div className="game-reference-header">{selection&&<input type="checkbox" aria-label={`Use reference ${label}`} checked={selection.ids.includes(selectionKey)} onChange={event=>selection.onChange(event.target.checked?[...selection.ids,selectionKey]:selection.ids.filter(id=>id!==selectionKey))}/>}<button className="text-button game-reference-toggle" type="button" aria-label={`Edit reference ${label}`} aria-expanded={expanded} aria-controls={`reference-editor-${reference.localId}`} onClick={() => setExpandedReferences(previous => { const next = new Set(previous); if (next.has(reference.localId)) next.delete(reference.localId); else next.add(reference.localId); return next; })}>{label}<span aria-hidden="true">{expanded ? '−' : '+'}</span></button><button className="text-button game-remove-reference" type="button" aria-label={`Remove reference ${label}`} title="Remove this reference, not its Library record" onClick={() => onChange({ ...draft, referencesTouched: true, references: draft.references.filter(item => item.localId !== reference.localId) })}>Remove</button></div>
          <SteamReferenceSource reference={reference.id ? base?.reference_works.find(item=>item.id===reference.id) : undefined} api={api}/>
          {expanded && <div id={`reference-editor-${reference.localId}`} className="game-reference-fields" role="group" aria-label={`Reference ${index + 1}`}>{referenceField(reference, 'name', 'Reference name')}{referenceField(reference, 'url', 'Reference URL')}{referenceField(reference, 'similarities', 'Similarities')}{referenceField(reference, 'reason', 'Reason')}</div>}
        </div>;
      })}
    </section></div>
    {base && <details className="game-provenance"><summary>Source comparison</summary><div className="game-source-binding"><h3>Source binding · Read-only</h3><dl><div><dt>Steam source</dt><dd>{base.source_identity.steam_app_id || 'Not bound'}</dd></div><div><dt>Source URL</dt><dd>{base.source_identity.canonical_url || 'Not bound'}</dd></div></dl></div><div className="game-source-comparisons">{GAME_FIELDS.map(key => <div className="game-source-field" key={key}><h4>{gameLabels[key]}{base.overridden_fields.includes(key) && <span className="game-source-badge">Manual override</span>}</h4><div><span>Source</span><p>{comparisonValue(base.source_fields[key])}</p></div><div><span>Current</span><p>{comparisonValue(key === 'tags' || key === 'languages' ? draft.fields[key].split('\n').filter(Boolean) : draft.fields[key] || null)}</p></div>{base.overridden_fields.includes(key) && <button className="button secondary" type="button" aria-label={`Use source ${gameLabels[key]}`} disabled={draft.resets.includes(key)} onClick={() => onChange({ ...draft, fields: { ...draft.fields, [key]: displayField(base.source_fields[key]) }, resets: [...new Set([...draft.resets, key])] })}>Use source</button>}</div>)}</div></details>}
  </fieldset>;
}
