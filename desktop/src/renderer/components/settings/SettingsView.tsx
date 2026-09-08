import { useCallback, useEffect, useRef, useState, type ComponentProps } from 'react';
import type { DesktopBridge } from '../../../shared/bridge';
import type { NavigationGuard } from '../../../shared/games';
import type { AppearanceState } from '../../hooks/useAppearance';
import { ConnectionSettings } from '../ConnectionSettings';
import { CloudSettings, type CloudDraftState } from './CloudSettings';
import { CollectionSettings } from './CollectionSettings';
import { AppearanceSettings, UpdateSettings } from './LocalSettings';
import { RefreshActivity } from './RefreshActivity';

const sections = [
  {id:'appearance',label:'Appearance',scope:'local'}, {id:'workspace',label:'Workspace',scope:'local'},
  {id:'services',label:'Services',scope:'shared'}, {id:'collection',label:'Collection',scope:'shared'}, {id:'refresh',label:'Auto-refresh',scope:'shared'},
  {id:'email',label:'Email',scope:'shared'}, {id:'updates',label:'Updates',scope:'local'},
] as const;
type Section = typeof sections[number]['id'];
type ConnectionProps = ComponentProps<typeof ConnectionSettings>;
export function SettingsView({api,active,available,workspaceEpoch,appearance,connection,collectionRequest=0,onNavigationGuardChange}: {
  api:DesktopBridge;active:boolean;available:boolean;workspaceEpoch:number;appearance:AppearanceState;
  connection:ConnectionProps;collectionRequest?:number;onNavigationGuardChange:(guard:NavigationGuard|null)=>void;
}) {
  // Workspace first preserves the most common recovery/connect entry. Category selection persists.
  const [section,setSection]=useState<Section>('workspace');
  const [lastShared,setLastShared]=useState<'services'|'collection'|'refresh'|'email'>('services');
  const [lastCloud,setLastCloud]=useState<'services'|'refresh'|'email'>('services');
  const [cloudFlags,setCloudFlags]=useState({dirty:false,busy:false});
  const [collectionFlags,setCollectionFlags]=useState({dirty:false,busy:false});
  const cloud=useRef<CloudDraftState>({dirty:false,busy:false,discard:()=>{}});
  const collection=useRef<CloudDraftState>({dirty:false,busy:false,discard:()=>{}});
  const [connectionDirty,setConnectionDirty]=useState(false);
  const [resetConnection,setResetConnection]=useState(0);
  const [leaving,setLeaving]=useState<null|'dirty'|'busy'>(null);
  const pending=useRef<(()=>void)|null>(null);
  const scrollPositions=useRef<Partial<Record<Section,number>>>({});
  const cloudChanged=useCallback((state:CloudDraftState)=>{
    cloud.current=state;
    setCloudFlags(previous=>previous.dirty===state.dirty&&previous.busy===state.busy?previous:{dirty:state.dirty,busy:state.busy});
  },[]);
  const collectionChanged=useCallback((state:CloudDraftState)=>{
    collection.current=state;
    setCollectionFlags(previous=>previous.dirty===state.dirty&&previous.busy===state.busy?previous:{dirty:state.dirty,busy:state.busy});
  },[]);
  const sharedBusy=cloudFlags.busy||collectionFlags.busy;
  const sharedDirty=cloudFlags.dirty||collectionFlags.dirty;
  const busy=sharedBusy||connection.phase==='saving';
  const dirty=connectionDirty||sharedDirty;
  const previousCollectionRequest=useRef(0);
  useEffect(()=>{
    onNavigationGuardChange(dirty||busy?(proceed)=>{pending.current=proceed;setLeaving(busy?'busy':'dirty');}:null);
    return()=>onNavigationGuardChange(null);
  },[dirty,busy,onNavigationGuardChange]);
  useEffect(()=>{if(connection.recovering)setSection('workspace');},[connection.recovering]);
  useEffect(()=>{
    if(collectionRequest===previousCollectionRequest.current)return;
    previousCollectionRequest.current=collectionRequest;
    if(collectionRequest>0&&!connection.recovering){
      choose('collection');
      if(active)requestAnimationFrame(()=>document.getElementById('settings-tab-collection')?.focus());
    }
  },[active,collectionRequest,connection.recovering]);
  useEffect(()=>{if(leaving==='busy'&&!busy){pending.current=null;setLeaving(null);}},[leaving,busy]);
  function choose(next:Section){
    const scroller=document.querySelector<HTMLElement>('.main-scroll');
    scrollPositions.current[section]=scroller?.scrollTop??0;
    setSection(next);
    if(next==='services'||next==='collection'||next==='refresh'||next==='email')setLastShared(next);
    if(next==='services'||next==='refresh'||next==='email')setLastCloud(next);
    requestAnimationFrame(()=>{if(scroller)scroller.scrollTop=scrollPositions.current[next]??0;});
  }
  function discard(){cloud.current.discard();collection.current.discard();setResetConnection(value=>value+1);setConnectionDirty(false);const proceed=pending.current;pending.current=null;setLeaving(null);proceed?.();}
  return <div className="settings-workspace">
    <div className="page-heading"><h1>Settings</h1></div>
    <div className="settings-layout">
      <div className="settings-categories" role="tablist" aria-label="Settings categories" onKeyDown={event=>{
        if(!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
        event.preventDefault();const index=sections.findIndex(item=>item.id===section);
        const next=event.key==='Home'?0:event.key==='End'?sections.length-1:(index+(['ArrowDown','ArrowRight'].includes(event.key)?1:-1)+sections.length)%sections.length;
        choose(sections[next].id);document.getElementById(`settings-tab-${sections[next].id}`)?.focus();
      }}>
        {sections.map(item=><button key={item.id} type="button" id={`settings-tab-${item.id}`} role="tab" aria-label={item.label} aria-selected={section===item.id} tabIndex={section===item.id?0:-1} aria-controls={`settings-panel-${item.id}`} onClick={()=>choose(item.id)}><span>{item.label}</span>{item.scope==='shared'&&<span className="category-shared">Shared</span>}</button>)}
      </div>
      <div className="settings-panels">
        <div id="settings-panel-appearance" role="tabpanel" aria-labelledby="settings-tab-appearance" hidden={section!=='appearance'}><AppearanceSettings state={appearance}/></div>
        <div id="settings-panel-workspace" role="tabpanel" aria-labelledby="settings-tab-workspace" hidden={section!=='workspace'}>
          {(sharedDirty||sharedBusy)&&<div className="settings-pending-notice" role="status"><span>{sharedBusy?'Shared settings action in progress.':'Unsaved shared settings'}</span><button className="text-button" onClick={()=>choose(collectionFlags.busy?'collection':cloudFlags.dirty||cloudFlags.busy?lastCloud:lastShared)}>Review settings</button></div>}
          <ConnectionSettings {...connection} embedded blocked={connection.blocked||sharedDirty||sharedBusy} resetSignal={resetConnection} onDraftStateChange={setConnectionDirty}/>
        </div>
        <div hidden={!['services','refresh','email'].includes(section)}><CloudSettings key={workspaceEpoch} api={api.settings} connected={available} active={active&&['services','refresh','email'].includes(section)} section={section==='services'||section==='refresh'||section==='email'?section:lastCloud} onDraftStateChange={cloudChanged}/></div>
        <CollectionSettings key={workspaceEpoch} api={api.settings} connected={available} active={active&&section==='collection'} onDraftStateChange={collectionChanged}/>
        <div hidden={section!=='refresh'}><RefreshActivity key={workspaceEpoch} api={api} connected={available}/></div>
        <div id="settings-panel-updates" role="tabpanel" aria-labelledby="settings-tab-updates" hidden={section!=='updates'}><UpdateSettings api={api} active={active&&section==='updates'} appearance={appearance}/></div>
      </div>
    </div>
    {leaving&&<SettingsLeaveDialog busy={leaving==='busy'} onCancel={()=>{pending.current=null;setLeaving(null);}} onDiscard={discard}/>}
  </div>;
}

function SettingsLeaveDialog({busy,onCancel,onDiscard}:{busy:boolean;onCancel:()=>void;onDiscard:()=>void}) {
  const panel=useRef<HTMLDivElement>(null);
  useEffect(()=>{const previous=document.activeElement as HTMLElement|null;panel.current?.querySelector('button')?.focus();return()=>previous?.focus();},[]);
  return <div className="modal-backdrop"><div ref={panel} className="confirm-dialog" role="dialog" aria-modal="true" aria-labelledby="settings-leave-title" onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();onCancel();}
    if(event.key==='Tab'){const buttons=panel.current?.querySelectorAll('button');if(!buttons?.length)return;const first=buttons[0],last=buttons[buttons.length-1];if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}}
  }}><h2 id="settings-leave-title">{busy?'Action in progress':'Unsaved settings'}</h2><p>{busy?'Wait for this action to finish before leaving.':'Discard unsaved settings and leave?'}</p><div className="button-row"><button className="button secondary" onClick={onCancel}>{busy?'Stay here':'Keep editing'}</button>{!busy&&<button className="button danger" onClick={onDiscard}>Discard changes</button>}</div></div></div>;
}
