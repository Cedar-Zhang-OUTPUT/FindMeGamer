import { useEffect, useRef, useState, type ReactNode } from 'react';
import { CREATOR_PLATFORMS, type CreatorPlatform } from '../../../shared/creators';
import { LANGUAGES } from '../match/discoveryConditionState';

const platformNames: Record<CreatorPlatform, string> = { youtube: 'YouTube', x: 'X', twitch: 'Twitch', instagram: 'Instagram' };
const languageName = (value: string) => LANGUAGES.find(([code]) => code === value)?.[1] ?? value;
const summary = (values: string[], name: (value: string) => string) => values.length ? values.map(name).join(', ') : 'Any';

function FilterDialog({ name, children, onCancel, onApply, invalid = false }: { name: string; children: ReactNode; onCancel: () => void; onApply: () => void; invalid?: boolean }) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>('input:not(:disabled),button:not(:disabled)')?.focus();
    return () => { if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  return <div className="creator-filter-backdrop"><div ref={panel} className="creator-filter-dialog" role="dialog" aria-modal="true" aria-label={name} onKeyDown={event => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); onCancel(); }
    if (event.key === 'Tab') {
      const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled)') ?? []);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}><h2>{name}</h2>{children}<div className="creator-filter-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button type="button" className="button primary" disabled={invalid} onClick={onApply}>Apply</button></div></div></div>;
}

export function PlatformFilter({ value, onApply }: { value: CreatorPlatform[]; onApply: (value: CreatorPlatform[]) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<CreatorPlatform[]>([]);
  function show() { setDraft([...value]); setOpen(true); }
  return <><button type="button" className="creator-filter-button" aria-label={`Platforms: ${summary(value, item => platformNames[item as CreatorPlatform])}`} aria-haspopup="dialog" onClick={show}><strong>Platforms</strong><span>{summary(value, item => platformNames[item as CreatorPlatform])}</span></button>{open && <FilterDialog name="Platforms" onCancel={() => setOpen(false)} onApply={() => { onApply(draft); setOpen(false); }}><div className="creator-filter-choices">{CREATOR_PLATFORMS.map(platform => <label key={platform}><input type="checkbox" checked={draft.includes(platform)} onChange={() => setDraft(draft.includes(platform) ? draft.filter(item => item !== platform) : [...draft, platform])} />{platformNames[platform]}</label>)}</div></FilterDialog>}</>;
}

export function LanguageFilter({ value, onApply }: { value: string[]; onApply: (value: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<string[]>([]);
  const [custom, setCustom] = useState('');
  const [error, setError] = useState('');
  function show() { setDraft([...value]); setCustom(''); setError(''); setOpen(true); }
  function toggle(language: string) { if (!draft.includes(language) && draft.length >= 30) return; setDraft(draft.includes(language) ? draft.filter(item => item !== language) : [...draft, language]); setError(''); }
  function add() {
    const next = custom.trim();
    if (!next || next.length > 255 || /[\u0000-\u001f\u007f]/.test(next)) { setError('Use 1–255 characters without control characters.'); return; }
    const duplicate = draft.some(item => item.toLocaleLowerCase() === next.toLocaleLowerCase());
    if (!duplicate && draft.length >= 30) { setError('Choose up to 30 languages.'); return; }
    if (!duplicate) setDraft([...draft, next]);
    setCustom(''); setError('');
  }
  const customChoices = draft.filter(value => !LANGUAGES.some(([code]) => code === value));
  return <><button type="button" className="creator-filter-button" aria-label={`Languages: ${summary(value, languageName)}`} aria-haspopup="dialog" onClick={show}><strong>Languages</strong><span>{summary(value, languageName)}</span></button>{open && <FilterDialog name="Languages" onCancel={() => setOpen(false)} invalid={Boolean(custom.trim())||draft.length>30} onApply={() => { onApply(draft); setOpen(false); }}><div className="creator-filter-choices creator-language-choices">{LANGUAGES.map(([code, label]) => <label key={code}><input type="checkbox" checked={draft.includes(code)} disabled={!draft.includes(code)&&draft.length>=30} onChange={() => toggle(code)} />{label} · {code}</label>)}{customChoices.map(language => <label key={language}><input type="checkbox" checked onChange={() => toggle(language)} />{language}</label>)}</div><div className="creator-filter-custom"><label>Other language<input value={custom} maxLength={255} onChange={event => { setCustom(event.target.value); setError(''); }} onKeyDown={event => { if (event.key === 'Enter') { event.preventDefault(); add(); } }} /></label><button type="button" className="button secondary" disabled={!custom.trim()} onClick={add}>Add</button></div>{draft.length>=30&&<p className="creator-filter-error" role="status">30 / 30 languages</p>}{error && <p className="creator-filter-error" role="alert">{error}</p>}</FilterDialog>}</>;
}
