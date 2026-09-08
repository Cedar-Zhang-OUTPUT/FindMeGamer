import type {CandidateQueryOptions,CandidateView,MatchAPI} from '../../../shared/match';
import type {Preparation,SelectionCancelChoice} from '../../../shared/outreach';
import type {PublicError} from '../../../shared/bridge';
const accountKey=(platform:string,account:string,revision:number)=>JSON.stringify([platform,account,revision]);
const candidateKey=(candidate:CandidateView)=>accountKey(candidate.platform,candidate.account_id,candidate.identity_revision);
const selectionKey=(selection:Preparation)=>accountKey(selection.identity.platform,selection.identity.account_id,selection.identity.revision);
export function candidateSelection(candidate:CandidateView,selections:Preparation[]):Preparation|undefined{
  if(candidate.identity_changed)return undefined;
  return selections.find(item=>item.active&&!item.identity_changed&&selectionKey(item)===candidateKey(candidate));
}
export function visibleSelections(candidates:CandidateView[],selections:Preparation[]):Preparation[]{
  const keys=new Set(candidates.filter(item=>!item.identity_changed).map(candidateKey));
  return selections.filter(item=>item.active&&!item.identity_changed&&keys.has(selectionKey(item)));
}
export function excludedSelections(previous:Preparation[],matching:CandidateView[]):SelectionCancelChoice[]{
  const keys=new Set(matching.filter(item=>!item.identity_changed).map(candidateKey));
  return previous.filter(item=>!keys.has(selectionKey(item))).map(item=>({selection_id:item.id,expected_revision:item.revision}));
}
export const membershipChanged:PublicError={code:'membership_changed',message:'Results changed while checking this filter. Try again; no people were removed.',retryable:true};
/** Complete, stable server membership is required before any explicit filter removal. */
export async function readCandidateMembership(api:Pick<MatchAPI,'candidates'>,queryId:string,options:Required<CandidateQueryOptions>):Promise<CandidateView[]>{
  const items:CandidateView[]=[],ids=new Set<string>();let total:number|undefined;
  for(let offset=0;offset<600;offset+=100){
    const result=await api.candidates({queryId,evidence:options.evidence,sort:'added',offset,limit:100});
    if(!result.ok)throw result.error;
    const page=result.data;
    if(page.offset!==offset||page.total>600||total!==undefined&&total!==page.total)throw membershipChanged;
    total=page.total;
    if(page.items.length!==Math.min(100,Math.max(0,total-offset)))throw membershipChanged;
    for(const item of page.items){if(ids.has(item.id))throw membershipChanged;ids.add(item.id);items.push(item);}
    if(items.length===total)return items;
  }
  throw membershipChanged;
}
