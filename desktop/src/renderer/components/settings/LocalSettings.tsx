import { useEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { UpdateState } from '../../../shared/preferences';
import type { AppearanceState } from '../../hooks/useAppearance';
import { ErrorNotice, Icon, Loading } from '../Primitives';

const releasesURL='https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases';
export function AppearanceSettings({state}:{state:AppearanceState}) {
  return <section className="settings-card" aria-labelledby="appearance-heading">
    <div className="section-heading"><h2 id="appearance-heading">Appearance</h2><span className="settings-scope">This Mac</span></div>
    <fieldset className="appearance-options" disabled={state.busy}><legend>Color scheme</legend>
      {(['system','light','dark'] as const).map(mode=><label className={`appearance-option ${mode}`} key={mode}>
        <input type="radio" name="appearance" value={mode} checked={state.preferences.appearance===mode} onChange={()=>void state.save({appearance:mode})}/>
        <span className="appearance-thumbnail" aria-hidden="true"><i/><span><b/><b/><b/></span></span>
        <span>{mode[0].toUpperCase()+mode.slice(1)}</span>
      </label>)}
    </fieldset>
    <div className="settings-control-row"><label htmlFor="text-size">Text size</label><select id="text-size" value={state.preferences.fontSize} disabled={state.busy} onChange={event=>void state.save({fontSize:event.target.value as typeof state.preferences.fontSize})}>
      <option value="small">Small</option><option value="medium">Medium</option><option value="default">Default</option><option value="large">Large</option><option value="extra-large">Extra large</option>
    </select></div>
    <div className="appearance-preview"><span className="preview-avatar" aria-hidden="true">F</span><strong>Find your next collaborator</strong></div>
    <button className="text-button" disabled={state.busy} onClick={()=>void state.save('restore')}>Restore appearance defaults</button>
    {state.error && <ErrorNotice error={state.error}/>}
  </section>;
}

export function UpdateSettings({api,active,appearance}:{api:DesktopBridge;active:boolean;appearance:AppearanceState}) {
  const [state,setState]=useState<UpdateState|null>(null);
  const [error,setError]=useState<PublicError|null>(null);
  const [checking,setChecking]=useState(false);
  const locked=useRef(false);
  const revision=useRef(0);
  const alive=useRef(true);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;revision.current++;};},[]);
  useEffect(()=>{
    if(!active)return;
    let live=true;
    async function read(){const token=++revision.current;try{const result=await api.updates.status();if(!live||locked.current||token!==revision.current)return;if(result.ok){setState(result.data);setError(null);}else setError(result.error);}catch{if(live)setError({code:'update_unavailable',message:'Could not read update status.',retryable:true});}}
    void read();
    const refresh=()=>void read(); window.addEventListener('focus',refresh);
    const timer=setInterval(refresh,2000);
    return()=>{live=false;clearInterval(timer);window.removeEventListener('focus',refresh);};
  },[active,api.updates]);
  async function check(){
    if(locked.current)return;locked.current=true;revision.current++;setChecking(true);setError(null);
    try{const result=await api.updates.check();if(!alive.current)return;if(result.ok)setState(result.data);else setError(result.error);}
    catch{if(alive.current)setError({code:'update_unavailable',message:'Could not check for updates. Try again.',retryable:true});}
    finally{locked.current=false;if(alive.current)setChecking(false);}
  }
  async function open(url:string){const result=await api.openExternal(url).catch(()=>null);if(!result?.ok)setError(result?.error??{code:'link_unavailable',message:'Could not open GitHub.',retryable:true});}
  const busy=checking||state?.phase==='checking';
  return <section className="settings-card" aria-labelledby="updates-heading">
    <div className="section-heading"><h2 id="updates-heading">Software updates</h2><span className="settings-scope">This Mac</span></div>
    {state?<><div className="update-identity"><img src="./assets/fox-mark.svg" alt=""/><div><strong>FindMeGamer</strong><span>Version {state.installedVersion}</span></div><span className="status-badge">{busy?'Checking…':state.phase==='current'?'Up to date':state.phase==='available'?`Version ${state.release?.version} available`:state.phase==='development'?'Development build':state.phase==='failed'?'Check failed':'Not checked'}</span></div>
      <div className="button-row"><button className="button secondary" disabled={busy} onClick={()=>void check()}>Check for updates</button>{state.release&&<button className="button primary" onClick={()=>void open(state.release!.url)}>Download {state.release.version}<Icon name="external"/></button>}</div>
      {state.release&&<p className="settings-note">Download from GitHub · Install manually.</p>}
      {state.lastCheckedAt&&<p className="settings-note">Last checked {new Date(state.lastCheckedAt).toLocaleString()}</p>}
      {state.error&&<ErrorNotice error={state.error}/>}
    </>:<Loading label="Reading update status…"/>}
    <label className="settings-toggle"><span>Automatically check for updates</span><input type="checkbox" checked={appearance.preferences.automaticUpdates} disabled={appearance.busy} onChange={event=>void appearance.save({automaticUpdates:event.target.checked})}/></label>
    {appearance.error&&<ErrorNotice error={appearance.error}/>}{error&&<ErrorNotice error={error}/>}
    <button className="text-button" onClick={()=>void open(releasesURL)}>All releases on GitHub<Icon name="external"/></button>
  </section>;
}
