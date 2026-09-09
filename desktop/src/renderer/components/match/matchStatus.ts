import type {QueryView} from '../../../shared/match';
import {queryIsRunning} from './useMatchSession';
export function canContinueQuery(query:QueryView){
  if(queryIsRunning(query)||query.result_count>=(query.conditions.result_limit??600))return false;
  const sources=Object.values(query.sources);
  if(sources.some(value=>{if(!value||typeof value!=='object'||Array.isArray(value))return false;const library=value.library;return library&&typeof library==='object'&&!Array.isArray(library)&&['pending','more'].includes(String(library.status));}))return true;
  if(query.requests_reserved>=(query.conditions.total_request_budget??120)||query.scanned_reserved>=(query.conditions.total_scan_budget??6000))return false;
  const states=sources.map(value=>value&&typeof value==='object'&&!Array.isArray(value)?value.status:null);
  return !states.length||!states.every(status=>['exhausted','not_supported','budget_exhausted'].includes(String(status)));
}
export const taskDate=(value:string)=>new Intl.DateTimeFormat('en',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(new Date(value));
const labels:Record<string,string>={queued:'Queued',running:'Discovering',paused:'Paused',completed:'Complete',stopped:'Stopped',outcome_unknown:'Outcome unknown',target_reached:'Batch complete',result_limit:'Result limit reached',total_budget_exhausted:'Budget reached',providers_finished:'Sources finished',provider_failed:'Source failed',source_partial:'Partial source results',source_unavailable:'Source unavailable',no_available_sources:'No available sources',budget_exhausted:'Batch budget reached',stopping:'Stopping',planning_model_unavailable:'Model unavailable',planning_output_invalid:'Planning failed',planning_rejected:'Planning rejected',planning_failed:'Planning failed',planning_outcome_unknown:'Planning outcome unknown',planning_discovery_queue_unavailable:'Discovery dispatch unavailable',missing_connection:'Not connected',not_supported:'Unavailable',exhausted:'Finished',more:'More available',ready:'Ready',failed:'Failed',partial:'Partial',unavailable:'Unavailable',no_matches:'No matches',screening:'Screening',evaluating:'Evaluating',ranking:'Grouping'};
export function taskLabel(value:string){return labels[value]??value.replaceAll('_',' ').replace(/^./,letter=>letter.toUpperCase());}
