import { useState } from 'react';
import { GAME_FIELDS, type GameDetail, type GameField } from '../../shared/games';
import { comparisonValue, displayField, gameLabels, newReference, type GameDraft, type ReferenceDraft } from './gameDraft';

export function GameForm({ base, draft, disabled, errors, onChange }: {
  base: GameDetail | null; draft: GameDraft; disabled: boolean; errors: Record<string, string>; onChange: (draft: GameDraft) => void;
}) {
  const [expandedReferences, setExpandedReferences] = useState<Set<string>>(new Set());
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
      <label htmlFor={props.id}>{gameLabels[field]}{draft.resets.includes(field) && <span className="game-source-badge">Will use source</span>}</label>
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
    <div className="game-editor-columns"><section className="game-primary-fields"><div className="game-fields-grid">{field('name')}{field('website_url')}{field('developer')}</div>{field('description')}{field('tags')}
      <details className="game-additional"><summary>More details</summary><div className="game-fields-grid">{field('steam_app_id')}{field('release_date')}{field('languages')}{field('cover_url')}</div>{base && <p className="game-binding-note">Website and Steam ID edits do not change the source binding.</p>}</details>
      <label className="game-favorite"><input type="checkbox" checked={draft.favorite} onChange={event => onChange({ ...draft, favorite: event.target.checked })}/>Saved</label>
    </section>
    <section className="game-references" aria-label="Reference works"><div className="game-section-title"><h3>Reference works <span className="count">{draft.references.length}</span></h3><button className="button secondary" type="button" disabled={draft.references.length >= 100} onClick={() => {
      const reference = newReference(); onChange({ ...draft, referencesTouched: true, references: [...draft.references, reference] }); setExpandedReferences(previous => new Set([...previous, reference.localId]));
      requestAnimationFrame(() => document.getElementById(`game-reference-${reference.localId}-name`)?.focus());
    }}>Add reference</button></div>
      {errors.references && <p className="game-field-error">{errors.references}</p>}
      {draft.references.map((reference, index) => {
        const label = reference.name.trim() || reference.url.trim() || `Reference ${index + 1}`;
        const hasError = Object.keys(errors).some(key => key.startsWith(`reference-${reference.localId}-`));
        const expanded = expandedReferences.has(reference.localId) || hasError;
        return <div className="game-reference-card" key={reference.localId}><div className="game-reference-header"><button className="text-button game-reference-toggle" type="button" aria-label={`Edit reference ${label}`} aria-expanded={expanded} aria-controls={`reference-editor-${reference.localId}`} onClick={() => setExpandedReferences(previous => { const next = new Set(previous); if (next.has(reference.localId)) next.delete(reference.localId); else next.add(reference.localId); return next; })}>{label}<span aria-hidden="true">{expanded ? '−' : '+'}</span></button><button className="text-button game-remove-reference" type="button" aria-label={`Remove reference ${label}`} title="Remove this reference, not its Library record" onClick={() => onChange({ ...draft, referencesTouched: true, references: draft.references.filter(item => item.localId !== reference.localId) })}>Remove</button></div>
          {expanded && <div id={`reference-editor-${reference.localId}`} className="game-reference-fields" role="group" aria-label={`Reference ${index + 1}`}>{referenceField(reference, 'name', 'Reference name')}{referenceField(reference, 'url', 'Reference URL')}{referenceField(reference, 'similarities', 'Similarities')}{referenceField(reference, 'reason', 'Reason')}</div>}
        </div>;
      })}
    </section></div>
    {base && <details className="game-provenance"><summary>Source comparison</summary><div className="game-source-binding"><h3>Source binding · Read-only</h3><dl><div><dt>Steam source</dt><dd>{base.source_identity.steam_app_id || 'Not bound'}</dd></div><div><dt>Source URL</dt><dd>{base.source_identity.canonical_url || 'Not bound'}</dd></div></dl></div><div className="game-source-comparisons">{GAME_FIELDS.map(key => <div className="game-source-field" key={key}><h4>{gameLabels[key]}{base.overridden_fields.includes(key) && <span className="game-source-badge">Manual override</span>}</h4><div><span>Source</span><p>{comparisonValue(base.source_fields[key])}</p></div><div><span>Current</span><p>{comparisonValue(key === 'tags' || key === 'languages' ? draft.fields[key].split('\n').filter(Boolean) : draft.fields[key] || null)}</p></div>{base.overridden_fields.includes(key) && <button className="button secondary" type="button" aria-label={`Use source ${gameLabels[key]}`} disabled={draft.resets.includes(key)} onClick={() => onChange({ ...draft, fields: { ...draft.fields, [key]: displayField(base.source_fields[key]) }, resets: [...new Set([...draft.resets, key])] })}>Use source</button>}</div>)}</div></details>}
  </fieldset>;
}
