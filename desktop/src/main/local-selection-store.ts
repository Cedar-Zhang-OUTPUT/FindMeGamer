import {createHash,randomUUID} from 'node:crypto';
import {mkdir,readFile,rename,rm,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import type {StoredConnection} from './credential-store';
import type {LocalSelectionContext,LocalSelectionsAPI} from '../shared/localSelections';
import type {LocalPrepareState} from '../renderer/components/match/localSelectionPrepare';

const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const revision=(value:unknown)=>Number.isInteger(value)&&Number(value)>=0;
const failure=(code:string,message:string)=>({ok:false as const,error:{code,message,retryable:false}});
/** Local-only draft journal. No network calls, credentials, settings or collections
 * are stored here. Per-query files keep pending choices out of other searches. */
export class LocalSelectionStore implements LocalSelectionsAPI {
  private queue:Promise<unknown>=Promise.resolve();
  constructor(private directory:string,private connection:()=>Promise<StoredConnection|null>){}
  async flush(){await this.queue;}
  private serial<T>(run:()=>Promise<T>){const work=this.queue.then(run);this.queue=work.catch(()=>{});return work;}
  private async context(input:LocalSelectionContext){
    if(!input||!uuid.test(input.activityId)||(input.queryId!==null&&!uuid.test(input.queryId)))throw Error('input');
    const connection=await this.connection();if(!connection)throw Error('connection');
    const scope=createHash('sha256').update(JSON.stringify([new URL(connection.serviceUrl).origin,connection.key])).digest('hex');
    const file=join(this.directory,'selection-drafts',scope,`${input.activityId}-${input.queryId??'none'}.json`);
    return {scope,file};
  }
  private valid(state:LocalPrepareState,scope:string,activityId:string){
    if(!state||!['ready','bulk_pending','readback','freeze_pending','conflict','done'].includes(state.stage)||state.draft?.scope!==scope||state.draft.activityId!==activityId||state.draft.version!==1||!Array.isArray(state.draft.desired)||!Array.isArray(state.draft.removed)||typeof state.draft.members!=='object'||!state.draft.members)return false;
    if(state.draft.desired.length>10000||state.draft.removed.length>10000||Object.keys(state.draft.members).length>10000)return false;
    if(new Set(state.draft.desired).size!==state.draft.desired.length||state.draft.desired.some(id=>!uuid.test(id)||!Object.hasOwn(state.draft.members,id)))return false;
    for(const member of Object.values(state.draft.members))if(!member||!uuid.test(member.candidateId)||!uuid.test(member.creatorId)||!member.identity||!['youtube','x','twitch','instagram'].includes(member.identity.platform)||typeof member.identity.account_id!=='string'||!Number.isInteger(member.identity.revision)||member.identity.revision<0)return false;
    for(const member of Object.values(state.draft.members))if(member.removal&&(!uuid.test(member.removal.selectionId)||!revision(member.removal.revision)))return false;
    if(state.stage==='bulk_pending'||state.stage==='freeze_pending'){
      if(!state.input||state.input.activityId!==activityId||!uuid.test(state.input.idempotencyKey)||!state.input.data)return false;
      if(state.stage==='bulk_pending'){
        if(!Number.isFinite(state.startedAt)||state.startedAt<0)return false;
        const adds=state.input.data.add_candidate_ids??[],cancels=state.input.data.cancel_selections??[];
        if(!Array.isArray(adds)||!Array.isArray(cancels)||adds.length>600||cancels.length>600||adds.length+cancels.length===0||adds.some(id=>!uuid.test(id))||cancels.some(item=>!item||!uuid.test(item.selection_id)||!revision(item.expected_revision)))return false;
      }else{
        const data=state.input.data;
        if(!uuid.test(data.request_id)||!Array.isArray(data.recipients)||!data.recipients.length||data.recipients.length>600||data.recipients.some(item=>!item||!uuid.test(item.selection_id)||!revision(item.expected_revision)||typeof item.context_token!=='string'||!/^[a-f0-9]{64}$/i.test(item.context_token)))return false;
      }
    }
    if(state.stage==='conflict'&&state.previous&&!this.valid(state.previous,scope,activityId))return false;
    if(state.stage==='done'&&(!state.batch||state.batch.activity_id!==activityId||!uuid.test(state.batch.id)||!uuid.test(state.batch.request_id)))return false;
    return true;
  }
  read(input:LocalSelectionContext){return this.serial(async()=>{
    try{const {scope,file}=await this.context(input);let state:LocalPrepareState|null=null;
      try{const source=await readFile(file,'utf8');if(source.length>8_000_000)throw Error('size');state=JSON.parse(source);if(!state||!this.valid(state,scope,input.activityId))throw Error('invalid');}
      catch(error){if((error as NodeJS.ErrnoException).code!=='ENOENT')return failure('local_selection_invalid','Saved local choices could not be read. They have not been overwritten.');}
      return {ok:true as const,data:{scope,state}};
    }catch{return failure('local_selection_unavailable','Local choices are unavailable. Check the workspace connection.');}
  });}
  write(input:Parameters<LocalSelectionsAPI['write']>[0]){return this.serial(async()=>{
    try{const {scope,file}=await this.context(input);
      if(input.scope!==scope)return failure('connection_changed','These local choices belong to another workspace.');
      if(!this.valid(input.state,scope,input.activityId))return failure('local_selection_invalid','The local selection state is invalid.');
      const encoded=JSON.stringify(input.state);if(encoded.length>8_000_000)return failure('local_selection_limit','Local preparation data exceeds the storage limit.');
      const dir=join(this.directory,'selection-drafts',scope);await mkdir(dir,{recursive:true,mode:0o700});const temporary=join(dir,`.${randomUUID()}.tmp`);
      try{await writeFile(temporary,encoded,{encoding:'utf8',mode:0o600,flag:'wx'});await rename(temporary,file);}finally{await rm(temporary,{force:true});}
      return {ok:true as const,data:undefined};
    }catch{return failure('local_selection_storage_failed','Could not save local choices. Keep this window open and retry.');}
  });}
}
