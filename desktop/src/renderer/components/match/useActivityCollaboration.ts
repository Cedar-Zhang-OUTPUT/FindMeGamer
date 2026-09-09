import {useCallback,useEffect,useRef,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {ActivityInvitation,ActivityInvitationPage,CollaborationAPI,CollaborationUpdate,ManualActivityResponse} from '../../../shared/collaboration';
import {useCollaborationOperation} from './useCollaborationOperation';
import type {CollaborationAttempt,CollaborationCommand} from './collaborationMutation';
export type InvitationFilters=Pick<Parameters<CollaborationAPI['list']>[0],'sending_state'|'invitation_state'|'follow_up_state'>;
export type ConfirmedCollaborationChange={activityId:string;selectionId:string;revision:number;kind:'update'|'respond'};
const readError:PublicError={code:'collaboration_read_failed',message:'Could not load invitations.',retryable:true};
export function useActivityCollaboration({api,activityId,active,blocked=false}:{api:CollaborationAPI;activityId:string;active:boolean;blocked?:boolean}){
 const operation=useCollaborationOperation(api);
 const [page,setPage]=useState<ActivityInvitationPage|null>(null),[filters,setFilters]=useState<InvitationFilters>({}),[offset,setOffset]=useState(0),[selectedId,setSelectedId]=useState<string|null>(null);
 const [invitation,setInvitation]=useState<ActivityInvitation|null>(null),[current,setCurrent]=useState(false),[loading,setLoading]=useState(false),[error,setError]=useState<PublicError|null>(null),[readback,setReadback]=useState<ActivityInvitation|null>(null);
 const [dirty,setDirty]=useState(false),[editorEpoch,setEditorEpoch]=useState(0),[confirmedChange,setConfirmedChange]=useState<ConfirmedCollaborationChange|null>(null);
 const alive=useRef(true),listVersion=useRef(0),detailVersion=useRef(0),epoch=useRef(0);
 const latest=useRef({active,blocked,selectedId,invitation,current,filters,offset,operation});latest.current={active,blocked,selectedId,invitation,current,filters,offset,operation};
 const invalidate=useCallback(()=>{listVersion.current++;detailVersion.current++;epoch.current++;latest.current.current=false;setCurrent(false);setLoading(false);setReadback(null);},[]);
 useEffect(()=>{alive.current=true;return()=>{alive.current=false;listVersion.current++;detailVersion.current++;};},[]);
 const readDetail=useCallback(async(id:string,recovery=false)=>{
  const token=++detailVersion.current;setCurrent(false);latest.current.current=false;setError(null);
  try{const result=await api.detail({activityId,selectionId:id});if(!alive.current||token!==detailVersion.current)return null;
   if(!result.ok){setError(result.error);return null;}const row=result.data;
   if(row.activity_id!==activityId||row.selection_id!==id){setError(readError);return null;}
   if(latest.current.selectedId===id){setInvitation(row);setCurrent(true);latest.current.invitation=row;latest.current.current=true;}
   if(recovery)setReadback(row);return row;
  }catch{if(alive.current&&token===detailVersion.current)setError(readError);return null;}
 },[activityId,api]);
 const load=useCallback(async()=>{
  const token=++listVersion.current;setLoading(true);setError(null);const options=latest.current;
  try{const result=await api.list({activityId,...options.filters,limit:50,offset:options.offset});if(!alive.current||token!==listVersion.current)return;
   if(result.ok&&result.data.items.every(row=>row.activity_id===activityId)){setPage(result.data);const last=Math.max(0,Math.floor((result.data.total-1)/50)*50);if(options.offset>last){setOffset(last);return;}
    if(!latest.current.selectedId&&result.data.items[0]){const id=result.data.items[0].selection_id;latest.current.selectedId=id;setSelectedId(id);void readDetail(id);}
   }else setError(result.ok?readError:result.error);
  }catch{if(alive.current&&token===listVersion.current)setError(readError);}
  finally{if(alive.current&&token===listVersion.current)setLoading(false);}
 },[activityId,api,readDetail]);
 useEffect(()=>{if(active){void load();if(latest.current.selectedId)void readDetail(latest.current.selectedId);}else invalidate();return()=>{listVersion.current++;detailVersion.current++;};},[active,filters,offset,load,readDetail,invalidate]);
 const select=useCallback((id:string)=>{if(latest.current.operation.busy||latest.current.operation.locked)return;latest.current.selectedId=id;setSelectedId(id);setReadback(null);void readDetail(id);},[readDetail]);
 const changeFilters=useCallback((next:InvitationFilters)=>{if(latest.current.operation.busy||latest.current.operation.locked)return;latest.current.filters=next;latest.current.offset=0;setFilters(next);setOffset(0);},[]);
 const changePage=useCallback((next:number)=>{if(latest.current.operation.busy||latest.current.operation.locked)return;latest.current.offset=next;setOffset(next);},[]);
 const accept=useCallback((row:ActivityInvitation,attempt?:CollaborationAttempt)=>{
  // A read started before commit cannot roll back an acknowledged revision.
  detailVersion.current++;
  if(latest.current.selectedId===row.selection_id){setInvitation(row);setCurrent(true);latest.current.invitation=row;latest.current.current=true;}
  if(attempt)setConfirmedChange({activityId:row.activity_id,selectionId:row.selection_id,revision:attempt.command.data.expected_revision,kind:attempt.command.kind});setReadback(null);setError(null);void load();
 },[load]);
 const submit=useCallback(async(kind:'update'|'respond',data:CollaborationUpdate|ManualActivityResponse)=>{
  const now=latest.current,row=now.invitation,version=epoch.current;if(!now.active||now.blocked||!now.current||!row||row.selection_id!==now.selectedId||row.revision!==data.expected_revision||now.operation.busy||now.operation.locked)return false;
  const command={kind,observed:row,data} as CollaborationCommand;const result=await now.operation.execute(command);
  if(!alive.current||version!==epoch.current)return false;
  if(result){accept(result);return true;}return false;
 },[accept]);
 const update=useCallback((data:CollaborationUpdate)=>submit('update',data),[submit]);const respond=useCallback((data:ManualActivityResponse)=>submit('respond',data),[submit]);
 const checkCurrent=useCallback(async()=>{const now=latest.current,attempt=now.operation.state.phase==='uncertain'?now.operation.state.attempt:null;const id=attempt?.command.observed.selection_id??now.selectedId;if(id)return readDetail(id,true);return null;},[readDetail]);
 const retryOriginal=useCallback(async()=>{const state=latest.current.operation.state;if(state.phase!=='uncertain')return;const version=epoch.current,result=await latest.current.operation.retry();if(alive.current&&version===epoch.current&&result)accept(result,state.attempt);},[accept]);
 const confirmCurrent=useCallback(()=>{if(!readback)return;const state=latest.current.operation.state;if(state.phase==='uncertain'&&latest.current.operation.confirmReadback(readback))accept(readback,state.attempt);},[readback,accept]);
 const reviewCurrent=useCallback(()=>{if(readback&&latest.current.operation.reviewReadback(readback)){setReadback(null);}},[readback]);
 const credentialsChanged=useCallback(()=>{operation.credentialsChanged();invalidate();},[operation.credentialsChanged,invalidate]);
 const discardEdits=useCallback(()=>{if(latest.current.operation.busy||latest.current.operation.locked)return;setDirty(false);setEditorEpoch(value=>value+1);},[]);
 return {page,filters,offset,selectedId,select,changeFilters,changePage,invitation,current,loading,error,readback,dirty,setDirty,editorEpoch,confirmedChange,operation,busy:operation.busy,locked:operation.locked,update,respond,checkCurrent,retryOriginal,confirmCurrent,reviewCurrent,credentialsChanged,discardEdits,refresh:load};
}
