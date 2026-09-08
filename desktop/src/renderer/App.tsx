import { useEffect, useRef, useState } from 'react';
import type { ConnectionInput, ConnectionStatus, DesktopBridge, PublicError } from '../shared/bridge';
import { ConnectionSettings, type ConnectionPhase } from './components/ConnectionSettings';
import { EmptyState, ErrorNotice, Icon, Loading, type IconName } from './components/Primitives';
import { LibraryView } from './components/LibraryView';

type Navigation = 'match' | 'outreach' | 'library' | 'settings';
const navigation: { id: Navigation; label: string; icon: IconName }[] = [
  { id: 'match', label: 'Match', icon: 'match' }, { id: 'outreach', label: 'Outreach', icon: 'outreach' },
  { id: 'library', label: 'Library', icon: 'library' }, { id: 'settings', label: 'Settings', icon: 'settings' },
];
const interrupted: PublicError = { code: 'desktop_unavailable', message: 'The desktop connection was interrupted. Try again.', retryable: true };

export function App() {
  const api: DesktopBridge | undefined = window.desktop;
  const [page, setPage] = useState<Navigation>('library');
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [phase, setPhase] = useState<ConnectionPhase>('loading');
  const [error, setError] = useState<PublicError | null>(null);
  const [route, setRoute] = useState<'direct' | 'proxy' | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [hasLibrarySession, setHasLibrarySession] = useState(false);
  const operation = useRef(0);
  const mounted = useRef(true);

  async function verify(token: number) {
    if (!api) return;
    setPhase('checking');
    try {
      const result = await api.connection.test();
      if (!mounted.current || operation.current !== token) return;
      if (result.ok) { setPhase('connected'); setHasLibrarySession(true); setRoute(result.data.route); setError(null); }
      else { setPhase('error'); setHasLibrarySession(false); setError(result.error); }
    } catch { if (mounted.current && operation.current === token) { setPhase('error'); setHasLibrarySession(false); setError(interrupted); } }
  }
  async function readStatus() {
    if (!api) return;
    const token = ++operation.current;
    setPhase('loading'); setHasLibrarySession(false); setError(null);
    try {
      const result = await api.connection.status();
      if (!mounted.current || operation.current !== token) return;
      if (!result.ok) { setPhase('error'); setError(result.error); return; }
      setStatus(result.data);
      if (result.data.hasKey) await verify(token); else setPhase('disconnected');
    } catch { if (mounted.current && operation.current === token) { setPhase('error'); setError(interrupted); } }
  }
  useEffect(() => {
    mounted.current = true;
    void readStatus();
    return () => { mounted.current = false; operation.current++; };
    // The preload bridge is fixed for the life of this renderer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api]);

  async function connect(input: ConnectionInput) {
    if (!api) return;
    if (status?.hasKey && !input.key && input.serviceUrl === status.serviceUrl) {
      testConnection();
      return;
    }
    const token = ++operation.current;
    setEpoch(previous => previous + 1); setHasLibrarySession(false); setPhase('saving'); setError(null); setRoute(null);
    try {
      const result = await api.connection.save(input);
      if (!mounted.current || operation.current !== token) return;
      if (!result.ok) { setPhase('error'); setError(result.error); return; }
      setStatus(result.data);
      if (!result.data.hasKey) { setPhase('disconnected'); return; }
      await verify(token);
    } catch { if (mounted.current && operation.current === token) { setPhase('error'); setError(interrupted); } }
  }
  function testConnection() {
    const token = ++operation.current;
    // Verifying unchanged credentials must not throw away list/profile context.
    // The retained Library stays hidden until verification succeeds; a failure clears it.
    setError(null); setRoute(null);
    void verify(token);
  }
  async function disconnect() {
    if (!api) return;
    const token = ++operation.current;
    setEpoch(previous => previous + 1); setHasLibrarySession(false); setPhase('disconnected'); setError(null); setRoute(null);
    try {
      const result = await api.connection.clear();
      if (!mounted.current || operation.current !== token) return;
      if (result.ok) setStatus(result.data); else { setPhase('error'); setError(result.error); }
    } catch { if (mounted.current && operation.current === token) { setPhase('error'); setError(interrupted); } }
  }
  const connected = phase === 'connected';
  if (!api) return <main className="browser-fallback"><img src="./assets/fox-mark.svg" alt=""/><span className="brand-name">FindMeGamer</span><EmptyState title="Open the desktop app">Workspace access is available in the installed FindMeGamer app.</EmptyState></main>;
  return <div className="app-shell">
    <aside className="sidebar" aria-label="Main navigation"><div className="window-titlebar" aria-hidden="true"/><div className="brand"><img src="./assets/fox-mark.svg" alt=""/><span>FindMeGamer</span></div>
      <nav>{navigation.slice(0, 3).map(item => <button key={item.id} className={`nav-button ${page === item.id ? 'selected' : ''}`} aria-label={item.label} aria-current={page === item.id ? 'page' : undefined} title={item.label} onClick={() => setPage(item.id)}><Icon name={item.icon}/><span>{item.label}</span></button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-connection" title={connected ? 'Workspace connected' : 'Workspace not connected'}><span className={`status-dot ${connected ? 'is-connected' : ''}`}/><span>{connected ? 'Workspace connected' : 'Not connected'}</span></div><button className={`nav-button ${page === 'settings' ? 'selected' : ''}`} aria-label="Settings" aria-current={page === 'settings' ? 'page' : undefined} title="Settings" onClick={() => setPage('settings')}><Icon name="settings"/><span>Settings</span></button></div>
    </aside>
    <div className="main-frame"><header className="landscape-header" aria-label="FindMeGamer"><div className="landscape-shade"/><span className="header-edition">WORKSPACE / 01</span></header>
      <main className="main-scroll" id="main-content">
        <section className="page-content" hidden={page !== 'library'} aria-label="Library page">{hasLibrarySession && <div hidden={!connected}><LibraryView key={epoch} api={api} active={page === 'library' && connected}/></div>}{!connected && <>
          <div className="page-heading"><div><span className="eyebrow">Your workspace</span><h1>Library</h1></div></div>
          {phase === 'loading' || phase === 'checking' || phase === 'saving' ? <Loading label={phase === 'loading' ? 'Opening workspace…' : 'Verifying connection…'}/> : <><EmptyState title="Connect your workspace" action={<button className="button primary" onClick={() => setPage('settings')}>Open Settings</button>}/>{error && <ErrorNotice error={error} onRetry={status?.hasKey ? testConnection : () => void readStatus()}/>}</>}
        </>}</section>
        <section className="page-content" hidden={page !== 'settings'} aria-label="Settings page"><ConnectionSettings status={status} phase={phase} error={error} route={route} onConnect={connect} onTest={testConnection} onDisconnect={() => void disconnect()} onLibrary={() => setPage('library')}/></section>
        {(['match', 'outreach'] as const).map(target => <section className="page-content" key={target} hidden={page !== target} aria-label={`${target} page`}><div className="page-heading"><div><span className="eyebrow">Workspace preview</span><h1>{target === 'match' ? 'Match' : 'Outreach'}</h1></div></div><div className="feature-unavailable"><span className="feature-icon"><Icon name={target}/></span><span className="status-badge">Not connected yet</span><button className="button primary" onClick={() => setPage('library')}>Open Library<Icon name="chevron"/></button></div></section>)}
      </main>
    </div>
  </div>;
}
