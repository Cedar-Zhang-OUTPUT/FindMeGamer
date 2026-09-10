import {useId,useRef,useState} from 'react';
import {CollaborationEditor} from './CollaborationEditor';
import type {ActivityInvitation} from '../../../shared/collaboration';
import type {InvitationFilters,useActivityCollaboration} from './useActivityCollaboration';
import {ErrorNotice,Loading} from '../Primitives';
import {reconcileCollaboration,reviewCollaboration} from './collaborationMutation';
import './collaborationWorkspace.css';
import './reviewTable.css';
const label=(s:string)=>s.replaceAll('_',' ');
function recordedWork(row:ActivityInvitation){
 const latest=row.memberships.reduce<ActivityInvitation['memberships'][number]|undefined>((found,item)=>!found||Date.parse(item.created_at)>Date.parse(found.created_at)?item:found,undefined);
 const works=latest?.snapshot.works;if(!Array.isArray(works)||!works.length)return '—';
 const work=works[0];if(!work||typeof work!=='object'||Array.isArray(work))return '—';
 const name=typeof work.work_name==='string'?work.work_name:typeof work.content_title==='string'?work.content_title:null;
 return name?name+(works.length>1?` +${works.length-1}`:''):'—';
}
export function CollaborationWorkspace({controller:c,active,onOpenCreator,onChoosePeople,onConnectionRepair}:{controller:ReturnType<typeof useActivityCollaboration>;active:boolean;onOpenCreator:(id:string)=>void;onChoosePeople:()=>void;onConnectionRepair?:()=>void}){
 const state=c.operation.state,attempt=state.phase==='uncertain'?state.attempt:null;
 const detailId=useId();
 const [editorOpen,setEditorOpen]=useState(false);
 const opener=useRef<HTMLButtonElement|null>(null);
 const recovery=<>{state.error&&<ErrorNotice error={state.error}/>} {c.busy&&<Loading label="Saving record…"/>}
  {(c.locked||state.error)&&<div className="collaboration-recovery"><button className="button secondary" disabled={c.busy} onClick={()=>void c.checkCurrent()}>Check current record</button>{c.locked&&<button className="button secondary" disabled={!c.operation.retryAllowed||c.busy} onClick={()=>void c.retryOriginal()}>Retry original request</button>}{onConnectionRepair&&<button className="text-button" onClick={onConnectionRepair}>Open Settings</button>}
    {attempt&&c.readback&&<><p>Current revision {c.readback.revision}</p><button disabled={!reconcileCollaboration(attempt,c.readback)||c.busy} onClick={c.confirmCurrent}>Confirm saved change</button><button disabled={!reviewCollaboration(attempt,c.readback)||c.busy} onClick={c.reviewCurrent}>Review newer version</button></>}
  </div>}</>;
 return <section hidden={!active} className="collaboration-workspace" aria-label="Invitations">
  <header className="collaboration-toolbar"><h2>Invitations</h2><button className="button secondary" disabled={c.busy||c.loading} onClick={()=>{void c.refresh();void c.checkCurrent();}}>Refresh invitations</button></header>
  <div className="collaboration-filters">{([
   ['sending_state','Sending',['not_sent','queued','sending','sent','failed','unknown']],['invitation_state','Response',['not_invited','awaiting_response','accepted','declined']],['follow_up_state','Follow-up',['not_followed_up','follow_up_needed','followed_up','no_follow_up_needed']],
  ] as const).map(([key,title,values])=><label key={key}>{title}<select value={c.filters[key]??''} disabled={c.busy||c.locked} onChange={e=>{const next:InvitationFilters={...c.filters};if(e.target.value)Object.assign(next,{[key]:e.target.value});else delete next[key];c.changeFilters(next);}}><option value="">All</option>{values.map(v=><option key={v} value={v}>{label(v)}</option>)}</select></label>)}</div>
  {c.loading&&<Loading label="Loading invitations…"/>}{c.error&&<ErrorNotice error={c.error} onRetry={()=>{void c.refresh();void c.checkCurrent();}}/>}
  {recovery}
  <div id={`${detailId}-table`} className="review-table-scroll" tabIndex={0} role="region" aria-label="Scrollable invitations"><table className="review-table" aria-label="Invitation relationships"><thead><tr>{['Creator','Platform','Recorded work','Sending','Invitation','Follow-up','Actions'].map(title=><th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{c.page?.items.map(row=><tr key={row.selection_id}>
    <th scope="row"><button className="text-button review-person" disabled={c.busy||c.locked} onClick={()=>onOpenCreator(row.creator_id)}>{row.display_name||'Unnamed creator'}</button>{!row.selected&&<span className="review-table-muted">Historical</span>}</th>
    <td>{row.identity.platform==='youtube'?'YouTube':row.identity.platform==='x'?'X':typeof row.identity.platform==='string'?row.identity.platform:'Unknown'}</td>
    <td>{recordedWork(row)}</td>
    <td><span aria-label={`Sending: ${label(row.sending_state)}`} className={`collaboration-state sending-${row.sending_state}`}>{label(row.sending_state)}</span></td>
    <td><span aria-label={`Response: ${label(row.invitation_state)}`} className={`collaboration-state response-${row.invitation_state}`}>{label(row.invitation_state)}</span></td>
    <td><span aria-label={`Follow-up: ${label(row.follow_up_state)}`} className="collaboration-state">{label(row.follow_up_state)}</span></td>
    <td><button className="text-button" aria-label={`Update relationship for ${row.display_name||'Unnamed creator'}`} aria-controls={detailId} aria-expanded={editorOpen&&c.selectedId===row.selection_id} disabled={c.busy||c.locked} onClick={event=>{opener.current=event.currentTarget;setEditorOpen(true);c.select(row.selection_id);requestAnimationFrame(()=>document.getElementById(detailId)?.focus());}}>Update</button></td>
  </tr>)}</tbody></table></div>
    {c.page?.items.length===0&&!c.loading&&<div><p>{Object.keys(c.filters).length?'No matching invitations':'No invitations yet'}</p>{!Object.keys(c.filters).length&&<button className="button secondary" onClick={onChoosePeople}>Choose creators</button>}</div>}
    {c.page&&c.page.total>0&&<div className="collaboration-pagination"><span>{c.page.offset+1}–{c.page.offset+c.page.items.length} / {c.page.total}</span><button disabled={c.busy||c.locked||c.loading||c.offset===0} onClick={()=>c.changePage(Math.max(0,c.offset-50))}>Previous</button><button disabled={c.busy||c.locked||c.loading||c.offset+50>=c.page.total} onClick={()=>c.changePage(c.offset+50)}>Next</button></div>}
  <section id={detailId} tabIndex={-1} className="collaboration-inline-editor" aria-label="Current invitation" hidden={!editorOpen}><button className="text-button" disabled={c.busy||c.locked||c.dirty} onClick={()=>{setEditorOpen(false);(opener.current?.isConnected?opener.current:document.getElementById(`${detailId}-table`))?.focus();}}>Close relationship</button>{c.invitation&&c.invitation.selection_id!==c.selectedId&&!c.error&&<Loading label="Loading relationship…"/>}{c.invitation?<CollaborationEditor key={c.editorEpoch} invitation={c.invitation} current={active&&c.current} busy={c.busy||c.locked} confirmedChange={c.confirmedChange} onUpdate={c.update} onRespond={c.respond} onDirtyChange={c.setDirty} onOpenCreator={()=>onOpenCreator(c.invitation!.creator_id)}/>:c.selectedId?<Loading label="Loading relationship…"/>:null}</section>
 </section>;
}
