import {CollaborationEditor} from './CollaborationEditor';
import type {InvitationFilters,useActivityCollaboration} from './useActivityCollaboration';
import {ErrorNotice,Loading} from '../Primitives';
import {reconcileCollaboration,reviewCollaboration} from './collaborationMutation';
import './collaborationWorkspace.css';
const label=(s:string)=>s.replaceAll('_',' ');
export function CollaborationWorkspace({controller:c,active,onOpenCreator,onChoosePeople,onConnectionRepair}:{controller:ReturnType<typeof useActivityCollaboration>;active:boolean;onOpenCreator:(id:string)=>void;onChoosePeople:()=>void;onConnectionRepair?:()=>void}){
 const state=c.operation.state,attempt=state.phase==='uncertain'?state.attempt:null;
 return <section hidden={!active} className="collaboration-workspace" aria-label="Invitations">
  <header className="collaboration-toolbar"><h2>Invitations</h2><button className="button secondary" disabled={c.busy||c.loading} onClick={()=>{void c.refresh();void c.checkCurrent();}}>Refresh invitations</button></header>
  <div className="collaboration-filters">{([
   ['sending_state','Sending',['not_sent','queued','sending','sent','failed','unknown']],['invitation_state','Response',['not_invited','awaiting_response','accepted','declined']],['follow_up_state','Follow-up',['not_followed_up','follow_up_needed','followed_up','no_follow_up_needed']],
  ] as const).map(([key,title,values])=><label key={key}>{title}<select value={c.filters[key]??''} disabled={c.busy||c.locked} onChange={e=>{const next:InvitationFilters={...c.filters};if(e.target.value)Object.assign(next,{[key]:e.target.value});else delete next[key];c.changeFilters(next);}}><option value="">All</option>{values.map(v=><option key={v} value={v}>{label(v)}</option>)}</select></label>)}</div>
  {c.loading&&<Loading label="Loading invitations…"/>}{c.error&&<ErrorNotice error={c.error} onRetry={()=>{void c.refresh();void c.checkCurrent();}}/>}
  {state.error&&<ErrorNotice error={state.error}/>} {c.busy&&<Loading label="Saving record…"/>}
  {(c.locked||state.error)&&<div className="collaboration-recovery"><button className="button secondary" disabled={c.busy} onClick={()=>void c.checkCurrent()}>Check current record</button>{c.locked&&<button className="button secondary" disabled={!c.operation.retryAllowed||c.busy} onClick={()=>void c.retryOriginal()}>Retry original request</button>}{onConnectionRepair&&<button className="text-button" onClick={onConnectionRepair}>Open Settings</button>}
    {attempt&&c.readback&&<><p>Current revision {c.readback.revision}</p><button disabled={!reconcileCollaboration(attempt,c.readback)||c.busy} onClick={c.confirmCurrent}>Confirm saved change</button><button disabled={!reviewCollaboration(attempt,c.readback)||c.busy} onClick={c.reviewCurrent}>Review newer version</button></>}
  </div>}
  <div className="collaboration-layout"><aside><ul aria-label="Invitation relationships">{c.page?.items.map(row=><li key={row.selection_id}><button aria-pressed={c.selectedId===row.selection_id} disabled={c.busy||c.locked} onClick={()=>c.select(row.selection_id)}><strong>{row.display_name||'Unnamed creator'}</strong><span>{label(row.invitation_state)}</span><small>{label(row.sending_state)} · {label(row.cooperation_state)}{!row.selected?' · Historical':''}</small></button></li>)}</ul>
    {c.page?.items.length===0&&!c.loading&&<div><p>{Object.keys(c.filters).length?'No matching invitations':'No invitations yet'}</p>{!Object.keys(c.filters).length&&<button className="button secondary" onClick={onChoosePeople}>Choose creators</button>}</div>}
    {c.page&&c.page.total>0&&<div className="collaboration-pagination"><span>{c.page.offset+1}–{c.page.offset+c.page.items.length} / {c.page.total}</span><button disabled={c.busy||c.locked||c.loading||c.offset===0} onClick={()=>c.changePage(Math.max(0,c.offset-50))}>Previous</button><button disabled={c.busy||c.locked||c.loading||c.offset+50>=c.page.total} onClick={()=>c.changePage(c.offset+50)}>Next</button></div>}
  </aside><div>{c.invitation?<CollaborationEditor key={c.editorEpoch} invitation={c.invitation} current={active&&c.current} busy={c.busy||c.locked} confirmedChange={c.confirmedChange} onUpdate={c.update} onRespond={c.respond} onDirtyChange={c.setDirty} onOpenCreator={()=>onOpenCreator(c.invitation!.creator_id)}/>:c.selectedId?<Loading label="Loading relationship…"/>:null}</div></div>
 </section>;
}
