import { CREATOR_PLATFORMS } from '../../../shared/creators';
import type { JsonObject, JsonValue } from '../../../shared/library';
import { canReset, entityFields, fieldLabel, sourceValue, updateDraftField, type EditContext, type EntityDraft } from './creatorDraft';
import './creatorForms.css';
export interface CreatorFormProps { context: EditContext; draft: EntityDraft; onChange: (draft: EntityDraft) => void; disabled: boolean; errors: Record<string, string> }
export function DraftField({ field, draft, onChange, errors, label = fieldLabel(field), value = draft.values[field], onValue, multiline = false, numeric = false, options, placeholder }: Pick<CreatorFormProps, 'draft' | 'onChange' | 'errors'> & { field: string; label?: string; value?: JsonValue; onValue?: (value: JsonValue) => void; multiline?: boolean; numeric?: boolean; options?: readonly string[]; placeholder?: string }) {
  const id = `creator-field-${field}`;
  const setValue = (next: JsonValue) => onValue ? onValue(next) : onChange(updateDraftField(draft, field, next));
  const props = { id, 'aria-label': label, 'aria-invalid': Boolean(errors[field]), 'aria-describedby': errors[field] ? `${id}-error` : undefined };
  const inputProps = { ...props, value: typeof value === 'string' || typeof value === 'number' ? value : '', placeholder, onChange: (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => setValue(numeric ? event.target.value === '' ? null : Number(event.target.value) : event.target.value || null) };
  return <div className={`form-field creator-form-field${multiline ? ' creator-wide-field' : ''}`}>
    <label htmlFor={id}>{label}</label>
    {typeof value === 'boolean' ? <input {...props} type="checkbox" checked={value} onChange={event => setValue(event.target.checked)}/> : options ? <select {...inputProps}>{options.map(option => <option key={option} value={option}>{option || 'Use creator platform'}</option>)}</select> : multiline ? <textarea {...inputProps} rows={3}/> : <input {...inputProps} type={numeric ? 'number' : 'text'} min={numeric ? 0 : undefined} step={field === 'follower_count' ? 1 : numeric ? 'any' : undefined} inputMode={numeric ? 'decimal' : undefined}/>}
    {draft.resets.includes(field) && <span className="creator-field-hint">Source selected</span>}
    {errors[field] && <span className="creator-field-error" id={`${id}-error`}>{errors[field]}</span>}
  </div>;
}
function displayValue(value: JsonValue | undefined): string {
  if (value === null || value === undefined || value === '') return 'Unknown';
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (Array.isArray(value)) return value.length ? value.map(displayValue).join(' · ') : 'None';
  if (typeof value === 'object') return Object.entries(value).filter(([, entry]) => entry !== null).map(([key, entry]) => `${fieldLabel(key)}: ${displayValue(entry)}`).join(', ');
  return String(value);
}
export function SourceComparison({ context, draft, onChange }: CreatorFormProps) {
  if (!context.base) return null;
  const overrides = context.base.manual_overrides;
  return <details className="creator-form-disclosure"><summary>Source comparison</summary><div className="creator-source-grid">{entityFields[context.kind].map(key => <section key={key} className="creator-source-field">
    <h4>{fieldLabel(key)}</h4>
    <dl><div><dt>Source</dt><dd>{displayValue(sourceValue(context, key))}</dd></div><div><dt>{Object.hasOwn(overrides, key) ? 'Manual' : 'Draft'}</dt><dd>{displayValue(draft.values[key])}</dd></div></dl>
    <button className="button secondary" type="button" aria-label={`Use source ${fieldLabel(key)}`} disabled={!canReset(context, key) || draft.resets.includes(key)} onClick={() => {
      const updated = updateDraftField(draft, key, sourceValue(context, key));
      onChange({ ...updated, resets: [...new Set([...updated.resets, key])] });
    }}>{!canReset(context, key) ? 'No source email' : draft.resets.includes(key) ? 'Source selected' : 'Use source'}</button>
  </section>)}</div></details>;
}
export function RepeatableFields({ field, draft, onChange, errors, metric = false }: Pick<CreatorFormProps, 'draft' | 'onChange' | 'errors'> & { field: 'other_contacts' | 'metrics'; metric?: boolean }) {
  const rows = (draft.values[field] ?? []) as JsonObject[];
  const change = (next: JsonObject[]) => onChange(updateDraftField(draft, field, next));
  return <div className="creator-repeatable"><span id={`creator-field-${field}`} tabIndex={-1}/>{errors[field] && <p className="creator-field-error">{errors[field]}</p>}
    {rows.map((row, index) => <fieldset key={index} className="creator-repeatable-row"><legend>{metric ? 'Metric' : 'Contact'} {index + 1}</legend><div className="creator-form-grid">
      {(metric ? ['name', 'value'] : ['label', 'value', 'url']).map(key => <DraftField key={key} field={`${field}-${index}-${key}`} draft={draft} onChange={onChange} errors={errors} value={row[key]} label={metric ? key === 'name' ? 'Metric name' : 'Metric value' : key === 'label' ? 'Contact label' : key === 'value' ? 'Contact value' : 'Contact URL'} numeric={metric && key === 'value'} onValue={value => change(rows.map((item, position) => position === index ? { ...item, [key]: value } : item))}/>)}
    </div><button type="button" className="text-button" aria-label={`Remove ${metric ? 'metric' : 'contact'} ${index + 1}`} onClick={() => change(rows.filter((_, position) => position !== index))}>Remove</button></fieldset>)}
    <button type="button" className="button secondary" disabled={rows.length >= (metric ? 30 : 100)} onClick={() => {
      change([...rows, metric ? { name: '', value: null } : { label: null, value: '', url: null }]);
      requestAnimationFrame(() => document.getElementById(`creator-field-${field}-${rows.length}-${metric ? 'name' : 'value'}`)?.focus());
    }}>Add {metric ? 'metric' : 'contact'}</button>
  </div>;
}
export function CreatorForm(props: CreatorFormProps) {
  const { context, draft, onChange, disabled, errors } = props;
  const field = (key: string, extra: Partial<React.ComponentProps<typeof DraftField>> = {}) => <DraftField key={key} {...props} field={key} {...extra}/>;
  const languages = (draft.values.languages ?? []) as string[];
  return <fieldset className="creator-form" disabled={disabled}><legend className="sr-only">Creator profile</legend>
    {!context.base && <div className="creator-form-grid">{field('platform', { options: CREATOR_PLATFORMS })}{field('account_id')}</div>}
    <div className="creator-form-grid">{field('name')}{field('profile_url')}</div>
    {field('favorite')}
    <details className="creator-form-disclosure"><summary>Display details</summary><div className="creator-form-grid">{field('public_name')}{field('public_name_confirmed')}{field('handle')}{field('avatar_url')}</div>{field('description', { multiline: true })}</details>
    <details className="creator-form-disclosure"><summary>Audience</summary><div className="creator-form-grid">{field('follower_count', { numeric: true, placeholder: 'Unknown' })}{field('follower_count_collected_at', { placeholder: '2026-09-08T12:00:00+08:00' })}{field('country_code', { placeholder: 'US' })}{field('country_name')}</div>
      <fieldset className="creator-repeatable"><legend>Languages</legend><span id="creator-field-languages" tabIndex={-1}/>{errors.languages && <p className="creator-field-error">{errors.languages}</p>}
        {languages.map((language, index) => <div className="creator-language-row" key={index}><DraftField {...props} field={`languages-${index}`} label={`Language ${index + 1}`} value={language} onValue={value => onChange(updateDraftField(draft, 'languages', languages.map((item, position) => position === index ? String(value ?? '') : item)))}/><button type="button" className="text-button" aria-label={`Remove language ${index + 1}`} onClick={() => onChange(updateDraftField(draft, 'languages', languages.filter((_, position) => position !== index)))}>Remove</button></div>)}
        <button type="button" className="button secondary" disabled={languages.length >= 100} onClick={() => onChange(updateDraftField(draft, 'languages', [...languages, '']))}>Add language</button>
      </fieldset>
    </details>
    <details className="creator-form-disclosure"><summary>Notes</summary>{field('source_notes', { multiline: true })}{field('internal_notes', { multiline: true })}{field('interest_notes', { multiline: true })}</details>
    <details className="creator-form-disclosure"><summary>Other contacts</summary><RepeatableFields {...props} field="other_contacts"/></details>
    <SourceComparison {...props}/>
  </fieldset>;
}
