import { useEffect, useRef, useState, type ReactNode } from 'react';
import type { PublicError } from '../../shared/bridge';

export type IconName = 'match' | 'outreach' | 'library' | 'settings' | 'search' | 'arrow' | 'external' | 'close' | 'check' | 'refresh' | 'chevron' | 'collection';
const paths: Record<IconName, ReactNode> = {
  match: <><path d="M8 3h8v5h5v8h-5v5H8v-5H3V8h5z"/><path d="m9 12 2 2 4-4"/></>,
  outreach: <><rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 6 9 7 9-7"/></>,
  library: <><rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 3v18m3-14h6m-6 4h6"/></>,
  settings: <><path d="m10 3-1 3-3 1-3 3v4l3 3 3 1 1 3h4l1-3 3-1 3-3v-4l-3-3-3-1-1-3z"/><circle cx="12" cy="12" r="3"/></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></>,
  arrow: <path d="M20 12H4m6-6-6 6 6 6"/>,
  external: <><path d="M14 3h7v7m0-7L10 14"/><path d="M10 5H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-5"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  check: <path d="m5 12 4 4L19 6"/>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6"/></>,
  chevron: <path d="m9 5 7 7-7 7"/>,
  collection: <path d="M6 3h12v18l-6-4-6 4z"/>,
};
export function Icon({ name, className = '' }: { name: IconName; className?: string }) {
  return <svg className={`icon ${className}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function ErrorNotice({ error, onRetry }: { error: PublicError; onRetry?: () => void }) {
  return <div className="error-notice" role="alert"><div><strong>{error.message}</strong>{error.correlationId && <details><summary>Error details</summary><code>{error.code} · {error.correlationId}</code></details>}</div>{onRetry && <button className="button secondary" onClick={onRetry}>Try again</button>}</div>;
}

export function Loading({ label }: { label: string }) {
  return <div className="loading-state" role="status"><span className="loading-mark" aria-hidden="true"/>{label}</div>;
}

export function EmptyState({ title, children, icon = 'library', action }: { title: string; children?: ReactNode; icon?: IconName; action?: ReactNode }) {
  return <div className="empty-state"><span className="empty-icon"><Icon name={icon}/></span><h2>{title}</h2>{children && <p>{children}</p>}{action}</div>;
}

export function Artwork({ url, name, kind, large = false }: { url: string | null; name: string; kind: 'games' | 'creators'; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [url]);
  let safeURL: string | undefined;
  try { const parsed = new URL(url || ''); if (parsed.protocol === 'https:' && !parsed.username && !parsed.password) safeURL = parsed.href; } catch { /* Missing artwork uses initials, not a fake portrait. */ }
  return <span className={`artwork ${kind} ${large ? 'large' : ''}`} aria-hidden="true">
    {safeURL && !failed ? <img src={safeURL} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)}/> : <span>{name.trim().slice(0, 2).toUpperCase() || '?'}</span>}
  </span>;
}

export function ConfirmDisconnect({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  const panel = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => { const previous = document.activeElement as HTMLElement | null; cancel.current?.focus(); return () => previous?.focus(); }, []);
  return <div className="modal-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onCancel(); }}>
    <div ref={panel} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="disconnect-title" onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); onCancel(); }
      if (event.key === 'Tab') { const buttons = panel.current?.querySelectorAll('button'); if (!buttons?.length) return; const first = buttons[0]; const last = buttons[buttons.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); } }
    }}>
      <h2 id="disconnect-title">Disconnect workspace?</h2><p>The saved key and this window’s loaded profiles will be cleared. Workspace data stays on the server.</p>
      <div className="button-row"><button ref={cancel} className="button secondary" onClick={onCancel}>Cancel</button><button className="button danger" onClick={onConfirm}>Disconnect</button></div>
    </div>
  </div>;
}

export function friendlyLabel(value: string): string {
  return value.replace(/[_-]+/g, ' ').replace(/([a-z])([A-Z])/g, '$1 $2').replace(/^./, first => first.toUpperCase());
}

export function analyzedDate(value: string | null): string {
  if (!value) return 'Not available';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}
