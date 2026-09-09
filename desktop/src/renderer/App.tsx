import { useEffect, useRef, useState } from 'react';
import type { ConnectionInput, ConnectionStatus, DesktopBridge, PublicError } from '../shared/bridge';
import { type ConnectionPhase } from './components/ConnectionSettings';
import { EmptyState, ErrorNotice, Icon, Loading, type IconName } from './components/Primitives';
import { LibraryView } from './components/LibraryView';
import { useNavigationGuard } from './hooks/useNavigationGuard';
import { useAppearance } from './hooks/useAppearance';
import { SettingsView } from './components/settings/SettingsView';
import { MatchWorkspace } from './components/match/MatchWorkspace';
import type {GameDetail} from '../shared/games';
import './settings.css';
import './settings-cloud.css';
import './appearance.css';

type Navigation = 'match' | 'outreach' | 'library' | 'settings';
const navigation: { id: Navigation; label: string; icon: IconName }[] = [
  { id: 'match', label: 'Match', icon: 'match' }, { id: 'outreach', label: 'Outreach', icon: 'outreach' },
  { id: 'library', label: 'Library', icon: 'library' }, { id: 'settings', label: 'Settings', icon: 'settings' },
];
const interrupted: PublicError = { code: 'desktop_unavailable', message: 'The desktop connection was interrupted. Try again.', retryable: true };

export function App() {
  const api: DesktopBridge | undefined = window.desktop;
  const appearance = useAppearance(api?.preferences);
  const [page, setPage] = useState<Navigation>('library');
  const [status, setStatus] = useState<ConnectionStatus | null>(null);
  const [phase, setPhase] = useState<ConnectionPhase>('loading');
  const [error, setError] = useState<PublicError | null>(null);
  const [route, setRoute] = useState<'direct' | 'proxy' | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [hasLibrarySession, setHasLibrarySession] = useState(false);
  const [recoveryOrigin, setRecoveryOrigin] = useState<string | null>(null);
  const [recoveryPage,setRecoveryPage]=useState<'library'|'match'>('library');
  const [collectionReturn,setCollectionReturn]=useState(false);
  const [collectionPage,setCollectionPage]=useState<'library'|'match'>('match');
  const [collectionRequest,setCollectionRequest]=useState(0);
  const [smtpRequest,setSMTPRequest]=useState(0);
  const [gameRequest,setGameRequest]=useState<{game:GameDetail;nonce:number}>();
  const gameRequestSequence=useRef(0);
  const operation = useRef(0);
  const mounted = useRef(true);
  const navigationGate = useNavigationGuard();
  const matchGate = useNavigationGuard();
  const settingsGate = useNavigationGuard();
  const taskGate=page==='match'||(page==='settings'&&(collectionReturn&&collectionPage==='match'||recoveryOrigin&&recoveryPage==='match'))?matchGate:navigationGate;
  const pageScroll = useRef<Record<Navigation, number>>({match:0,outreach:0,library:0,settings:0});
  function useGameForMatch(game:GameDetail){
    navigationGate.request(()=>{
      pageScroll.current.library=document.querySelector<HTMLElement>('.main-scroll')?.scrollTop??0;
      setPage('match');
      // Reveal the retained Match task before it asks to discard its own draft.
      matchGate.request(()=>setGameRequest({game,nonce:++gameRequestSequence.current}));
    });
  }
  function navigate(target: Navigation) {
    if (page === target) return;
    const proceed = () => {
      const scroller = document.querySelector<HTMLElement>('.main-scroll');
      pageScroll.current[page] = scroller?.scrollTop ?? 0;
      setPage(target);
      requestAnimationFrame(() => { if (scroller) scroller.scrollTop = pageScroll.current[target]; });
    };
    // Collection is a same-workspace detour: retain Match and fence connection changes.
    if (collectionReturn && page==='settings') {
      settingsGate.request(()=>{
        setCollectionReturn(false);
        if(target===collectionPage)proceed();
        else {
          // The retained task owns its dialog; reveal it before asking to leave.
          setPage(collectionPage);
          taskGate.request(proceed);
        }
      });
    // A task can lend navigation to credential repair without surrendering its draft.
    } else if (target === 'settings' && status?.serviceUrl && taskGate.getRecovery()) {
      setRecoveryOrigin(status.serviceUrl);setRecoveryPage(page==='match'?'match':'library'); proceed();
    } else if (target === recoveryPage && recoveryOrigin) {
      settingsGate.request(()=>{setRecoveryOrigin(null); proceed();});
    } else if(page==='settings') settingsGate.request(()=>taskGate.request(()=>{setRecoveryOrigin(null);proceed();}));
    else taskGate.request(() => { setRecoveryOrigin(null); proceed(); });
  }
  function openCollectionSettings() {
    if(page!=='match'&&page!=='library')return;
    pageScroll.current[page]=document.querySelector<HTMLElement>('.main-scroll')?.scrollTop??0;
    setCollectionPage(page);setRecoveryOrigin(null);setCollectionReturn(true);setCollectionRequest(value=>value+1);setPage('settings');
  }
  function openSMTPSettings() {
    if(page!=='match')return;
    pageScroll.current.match=document.querySelector<HTMLElement>('.main-scroll')?.scrollTop??0;
    setCollectionPage('match');setRecoveryOrigin(null);setCollectionReturn(true);setSMTPRequest(value=>value+1);setPage('settings');
  }

  async function verify(token: number) {
    if (!api) return;
    setPhase('checking');
    try {
      const result = await api.connection.test();
      if (!mounted.current || operation.current !== token) return;
      if (result.ok) { setPhase('connected'); setHasLibrarySession(true); setRoute(result.data.route); setError(null); }
      else { setPhase('error'); if (!navigationGate.hasPending()&&!matchGate.hasPending()&&!settingsGate.hasPending()) setHasLibrarySession(false); setError(result.error); }
    } catch { if (mounted.current && operation.current === token) { setPhase('error'); if (!navigationGate.hasPending()&&!matchGate.hasPending()&&!settingsGate.hasPending()) setHasLibrarySession(false); setError(interrupted); } }
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
    if (!api || collectionReturn) return;
    const recovery = recoveryOrigin ? (recoveryPage==='match'?matchGate:navigationGate).getRecovery() : undefined;
    if (recoveryOrigin && (!recovery || input.serviceUrl !== recoveryOrigin)) return;
    if (status?.hasKey && !input.key && input.serviceUrl === status.serviceUrl) {
      testConnection();
      return;
    }
    const token = ++operation.current;
    if (!recovery) { setGameRequest(undefined); setEpoch(previous => previous + 1); setHasLibrarySession(false); }
    setPhase('saving'); setError(null); setRoute(null);
    try {
      const result = await api.connection.save(input);
      if (!mounted.current || operation.current !== token) return;
      if (!result.ok) { setPhase('error'); setError(result.error); return; }
      recovery?.credentialsChanged();
      setStatus(result.data);
      if (!result.data.hasKey) { setPhase('disconnected'); return; }
      await verify(token);
    } catch { if (mounted.current && operation.current === token) { setPhase('error'); setError(interrupted); } }
  }
  function testConnection() {
    if(collectionReturn)return;
    const token = ++operation.current;
    // Verifying unchanged credentials must not throw away list/profile context.
    // The retained Library stays hidden until verification succeeds; a failure clears it.
    setError(null); setRoute(null);
    void verify(token);
  }
  async function disconnect() {
    if (!api || recoveryOrigin || collectionReturn) return;
    const token = ++operation.current;
    setGameRequest(undefined); setEpoch(previous => previous + 1); setHasLibrarySession(false); setPhase('disconnected'); setError(null); setRoute(null);
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
      <nav>{navigation.slice(0, 3).map(item => <button key={item.id} className={`nav-button ${page === item.id ? 'selected' : ''}`} aria-label={item.label} aria-current={page === item.id ? 'page' : undefined} title={item.label} onClick={() => navigate(item.id)}><Icon name={item.icon}/><span>{item.label}</span></button>)}</nav>
      <div className="sidebar-bottom"><div className="sidebar-connection" title={connected ? 'Workspace connected' : 'Workspace not connected'}><span className={`status-dot ${connected ? 'is-connected' : ''}`}/><span>{connected ? 'Workspace connected' : 'Not connected'}</span></div><button className={`nav-button ${page === 'settings' ? 'selected' : ''}`} aria-label="Settings" aria-current={page === 'settings' ? 'page' : undefined} title="Settings" onClick={() => navigate('settings')}><Icon name="settings"/><span>Settings</span></button></div>
    </aside>
    <div className="main-frame"><header className="landscape-header" aria-label="FindMeGamer"><div className="landscape-shade"/></header>
      <main className="main-scroll" id="main-content">
        <section className="page-content" hidden={page !== 'library'} aria-label="Library page">{hasLibrarySession && <div hidden={!connected}><LibraryView key={epoch} api={api} active={page === 'library' && connected} onUseForMatch={useGameForMatch} onNavigationGuardChange={navigationGate.register} onConnectionRepair={() => navigate('settings')} onCollectionSettings={openCollectionSettings}/></div>}{!connected && <>
          <div className="page-heading"><h1>Library</h1></div>
          {phase === 'loading' || phase === 'checking' || phase === 'saving' ? <Loading label={phase === 'loading' ? 'Opening workspace…' : 'Verifying connection…'}/> : <><EmptyState title="Connect your workspace" action={<button className="button primary" onClick={() => navigate('settings')}>Open Settings</button>}/>{error && <ErrorNotice error={error} onRetry={status?.hasKey ? testConnection : () => void readStatus()}/>}</>}
        </>}</section>
        <section className="page-content" hidden={page !== 'settings'} aria-label="Settings page"><SettingsView api={api} active={page==='settings'} available={hasLibrarySession&&Boolean(status?.hasKey)} workspaceEpoch={epoch} appearance={appearance} collectionRequest={collectionRequest} smtpRequest={smtpRequest} onNavigationGuardChange={settingsGate.register} connection={{status,phase,error,route,blocked:collectionReturn,recovering:Boolean(recoveryOrigin),onConnect:connect,onTest:testConnection,onDisconnect:()=>void disconnect(),returnLabel:collectionReturn?(collectionPage==='match'?'Return to Match':'Return to Library'):recoveryOrigin&&recoveryPage==='match'?'Return to Match':undefined,onLibrary:()=>navigate(collectionReturn?collectionPage:recoveryOrigin?recoveryPage:'library')}}/></section>
        <section className="page-content" hidden={page!=='match'} aria-label="match page">{hasLibrarySession&&<div hidden={!connected}><MatchWorkspace key={epoch} api={api} active={page==='match'&&connected} gameRequest={gameRequest} onGameRequestHandled={()=>setGameRequest(undefined)} onNavigationGuardChange={matchGate.register} onConnectionRepair={()=>navigate('settings')} onCollectionSettings={openCollectionSettings} onSMTPSettings={openSMTPSettings}/></div>}{!connected&&<><div className="page-heading"><h1>Match</h1></div>{phase==='loading'||phase==='checking'||phase==='saving'?<Loading label="Opening workspace…"/>:<><EmptyState title="Connect your workspace" action={<button className="button primary" onClick={()=>navigate('settings')}>Open Settings</button>}/>{error&&<ErrorNotice error={error} onRetry={status?.hasKey?testConnection:()=>void readStatus()}/>}</>}</>}</section>
        <section className="page-content" hidden={page!=='outreach'} aria-label="outreach page"><div className="page-heading"><h1>Outreach</h1></div><div className="feature-unavailable"><span className="feature-icon"><Icon name="outreach"/></span><span className="status-badge">Not connected yet</span><button className="button primary" onClick={()=>navigate('library')}>Open Library<Icon name="chevron"/></button></div></section>
      </main>
    </div>
  </div>;
}
