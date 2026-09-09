import type {PublicError} from '../../../shared/bridge';
import type {ActivityInvitation,CollaborationAPI,CollaborationUpdate,ManualActivityResponse} from '../../../shared/collaboration';

export type CollaborationCommand={kind:'update';observed:ActivityInvitation;data:CollaborationUpdate}|{kind:'respond';observed:ActivityInvitation;data:ManualActivityResponse};
export interface CollaborationAttempt {readonly command:CollaborationCommand;readonly input:Parameters<CollaborationAPI['update']>[0]|Parameters<CollaborationAPI['respond']>[0];readonly startedAt:number;readonly connectionChanged:boolean}
export const COLLABORATION_RETRY_WINDOW=86_400_000;
export const collaborationUnknown:PublicError={code:'collaboration_write_unknown',message:'Save not confirmed. Check the record or retry the original request.',retryable:false};
export const collaborationChanged:PublicError={code:'connection_changed',message:'Connection changed. Check this record in the original workspace.',retryable:false};
export const collaborationMismatch:PublicError={code:'collaboration_reconciliation_mismatch',message:'The current record does not confirm this change.',retryable:false};
function freeze<T>(value:T):T{if(value&&typeof value==='object'){for(const item of Object.values(value))freeze(item);Object.freeze(value);}return value;}
export function freezeCollaborationAttempt(command:CollaborationCommand,startedAt=Date.now(),idempotencyKey=crypto.randomUUID()):CollaborationAttempt{
 const copy=structuredClone(command);return freeze({command:copy,input:{activityId:copy.observed.activity_id,selectionId:copy.observed.selection_id,data:copy.data,idempotencyKey},startedAt,connectionChanged:false});
}
export function fenceCollaboration(attempt:CollaborationAttempt):CollaborationAttempt{return freeze({...attempt,connectionChanged:true});}
export function canRetryCollaboration(attempt:CollaborationAttempt){const age=Date.now()-attempt.startedAt;return !attempt.connectionChanged&&age>=0&&age<COLLABORATION_RETRY_WINDOW;}
export function collaborationUncertain(code:string){return ['collaboration_write_unknown','network_error','connection_changed'].includes(code);}
export function dispatchCollaboration(api:CollaborationAPI,attempt:CollaborationAttempt){return attempt.command.kind==='update'?api.update(attempt.input as Parameters<CollaborationAPI['update']>[0]):api.respond(attempt.input as Parameters<CollaborationAPI['respond']>[0]);}
function canonical(v:unknown):string{return v===null||typeof v!=='object'?JSON.stringify(v):Array.isArray(v)?`[${v.map(canonical).join(',')}]`:`{${Object.entries(v).sort(([a],[b])=>a.localeCompare(b)).map(([k,x])=>`${JSON.stringify(k)}:${canonical(x)}`).join(',')}}`;}
// Preserve PostgreSQL microseconds; Date.parse alone silently discards evidence precision.
function timestamp(v:string):string|null{const match=/^(.*T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(v);if(!match)return null;const seconds=Date.parse(match[1]+match[3]);return Number.isFinite(seconds)?`${seconds}:${(match[2]??'').padEnd(6,'0')}`:null;}
function sameScope(a:CollaborationAttempt,row:ActivityInvitation){const old=a.command.observed;return row.activity_id===old.activity_id&&row.selection_id===old.selection_id&&row.creator_id===old.creator_id&&canonical(row.identity)===canonical(old.identity);}
export function reconcileCollaboration(attempt:CollaborationAttempt,row:ActivityInvitation):boolean{
 if(!sameScope(attempt,row))return false;const c=attempt.command,old=c.observed;
 if(c.kind==='update')return row.revision===c.data.expected_revision+1&&row.follow_up_state===(c.data.follow_up_state??old.follow_up_state)&&row.cooperation_state===(c.data.cooperation_state??old.cooperation_state)&&row.notes===(c.data.notes??old.notes)&&canonical(row.responses)===canonical(old.responses);
 const matches=row.responses.filter(event=>event.revision===c.data.expected_revision+1&&event.outcome===c.data.outcome&&event.source_note===c.data.source_note&&timestamp(event.responded_at)!==null&&timestamp(event.responded_at)===timestamp(c.data.responded_at)&&!old.responses.some(previous=>previous.id===event.id));
 return row.revision>=c.data.expected_revision+1&&matches.length===1&&old.responses.every(previous=>row.responses.some(event=>canonical(previous)===canonical(event)));
}
/** Explicitly retire the stale old-revision intent; this does not claim it succeeded. */
export function reviewCollaboration(attempt:CollaborationAttempt,row:ActivityInvitation){return sameScope(attempt,row)&&row.revision>attempt.command.data.expected_revision;}
export function validCollaborationCommand(c:CollaborationCommand){return c.data.expected_revision===c.observed.revision&&(c.kind==='respond'?!!c.data.source_note.trim()&&c.data.source_note===c.data.source_note.trim()&&timestamp(c.data.responded_at)!==null:Object.keys(c.data).some(key=>key!=='expected_revision'));}
