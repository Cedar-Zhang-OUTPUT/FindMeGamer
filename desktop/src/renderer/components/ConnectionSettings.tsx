import { useEffect, useState } from 'react';
import type { ConnectionInput, ConnectionStatus, PublicError } from '../../shared/bridge';
import { ConfirmDisconnect, ErrorNotice, Icon, Loading } from './Primitives';

export type ConnectionPhase = 'loading' | 'disconnected' | 'saving' | 'checking' | 'connected' | 'error';
export function ConnectionSettings({ status, phase, error, route, onConnect, onTest, onDisconnect, onLibrary }: {
  status: ConnectionStatus | null; phase: ConnectionPhase; error: PublicError | null; route: 'direct' | 'proxy' | null;
  onConnect: (input: ConnectionInput) => Promise<void>; onTest: () => void; onDisconnect: () => void; onLibrary: () => void;
}) {
  const [serviceUrl, setServiceUrl] = useState(status?.serviceUrl ?? '');
  const [key, setKey] = useState('');
  const [confirming, setConfirming] = useState(false);
  useEffect(() => setServiceUrl(status?.serviceUrl ?? ''), [status?.serviceUrl]);
  const busy = phase === 'loading' || phase === 'saving' || phase === 'checking';
  const dirty = serviceUrl.trim() !== (status?.serviceUrl ?? '') || key.length > 0;
  const hasExistingKey = Boolean(status?.hasKey);
  return <>
    <div className="page-heading"><div><span className="eyebrow">Workspace</span><h1>Settings</h1></div></div>
    <section className="settings-panel" aria-label="Workspace connection"><div className="section-heading"><h2>Connection</h2><span className={`status-badge ${phase === 'connected' ? 'connected' : ''}`}><span className="status-dot"/>{phase === 'connected' ? 'Connected' : busy ? 'Checking' : 'Not connected'}</span></div>
      <form onSubmit={event => { event.preventDefault(); if (busy) return; const submittedKey = key; setKey(''); void onConnect({ serviceUrl: serviceUrl.trim(), ...(submittedKey ? { key: submittedKey } : {}) }); }}>
        <div className="form-field"><label htmlFor="service-url">Service URL</label><input id="service-url" type="url" required placeholder="https://your-workspace.example.com" value={serviceUrl} onChange={event => setServiceUrl(event.target.value)} disabled={busy} spellCheck={false} autoComplete="off"/></div>
        <div className="form-field"><label htmlFor="workspace-key">Workspace key {hasExistingKey && <span className="saved-key"><Icon name="check"/>Saved securely</span>}</label><input id="workspace-key" type="password" aria-label="Workspace key" value={key} onChange={event => setKey(event.target.value)} placeholder={hasExistingKey ? 'Leave blank to keep saved key' : 'Enter workspace key'} required={!hasExistingKey} disabled={busy || status?.storageAvailable === false} autoComplete="off" spellCheck={false}/></div>
        {status?.storageAvailable === false && <div className="inline-warning" role="alert">Secure storage is unavailable. A workspace key cannot be saved on this device.</div>}
        <div className="connection-actions"><button className="button primary" type="submit" disabled={busy || status?.storageAvailable === false || !serviceUrl.trim() || (!key && !hasExistingKey)}>{phase === 'saving' ? 'Saving…' : phase === 'checking' ? 'Connecting…' : 'Connect'}</button>{hasExistingKey && <button className="button secondary" type="button" disabled={busy || dirty} onClick={onTest}>Test connection</button>}{hasExistingKey && <button className="text-button disconnect-action" type="button" disabled={busy} onClick={() => setConfirming(true)}>Disconnect</button>}</div>
      </form>
      {error && <ErrorNotice error={error} onRetry={hasExistingKey && !dirty ? onTest : undefined}/>}
      {phase === 'connected' && <div className="verified-state" role="status"><Icon name="check"/><div><strong>Connection verified</strong><span>System proxy · {route === 'proxy' ? 'Proxy route' : 'Direct route'}</span></div><button className="text-button" onClick={onLibrary}>Open Library<Icon name="chevron"/></button></div>}
      {phase === 'checking' && <Loading label="Saved · Verifying workspace…"/>}
      {phase === 'disconnected' && hasExistingKey && <p className="muted" role="status">Saved · Not checked</p>}
    </section>
    <div className="settings-footnote"><Icon name="library"/><span>Library access is read-only in this preview.</span></div>
    {confirming && <ConfirmDisconnect onCancel={() => setConfirming(false)} onConfirm={() => { setConfirming(false); setKey(''); onDisconnect(); }}/>}
  </>;
}
