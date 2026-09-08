import {vi} from 'vitest';
import type {MatchAPI,ActivityView,PlanView,QueryView,EvaluationView,CandidateView} from '../src/shared/match';
import {creatorFixture} from './creator-fixtures';
const ok=<T>(data:T)=>({ok:true as const,data});

export const activityFixture=(id='10000000-0000-4000-8000-000000000001'):ActivityView=>({id,name:'Indie launch',game_id:'10000000-0000-4000-8000-000000000002',source_snapshot:{game:{name:'A game',description:'An atmospheric adventure'},reference_works:[]},created_at:'2026-09-08T00:00:00Z'});
export const planFixture=(status:PlanView['status']='ready'):PlanView=>({id:'10000000-0000-4000-8000-000000000003',activity_id:activityFixture().id,status,conditions:{mode:'discover',platforms:['youtube'],batch_target:100,result_limit:600},source_snapshot:activityFixture().source_snapshot,output:{summary:'Indie adventure creators',rationale:'Related games',queries:[{platform:'youtube',terms:['indie adventure']}],provider_queries:{youtube:'indie adventure'}},error_code:null,retryable:false,attempt:1,model:'DeepSeek Flash',query_id:'10000000-0000-4000-8000-000000000004',created_at:'2026-09-08T01:00:00Z'});
export const queryFixture=(status='paused'):QueryView=>({id:planFixture().query_id!,activity_id:activityFixture().id,conditions:{providers:[{platform:'youtube',query:'indie adventure'}],batch_target:100,result_limit:600,total_request_budget:120,total_scan_budget:6000},source_snapshot:activityFixture().source_snapshot,status,stop_requested:false,requires_acknowledgement:false,result_count:2,requests_reserved:2,scanned_reserved:25,sources:{youtube:{status:'more'}},batches:[],usage:{requests_used:2,provider_items_received:25,unknown_requests_reserved:0},created_at:'2026-09-08T01:00:00Z'});
export const evaluationFixture=():EvaluationView=>({id:'10000000-0000-4000-8000-000000000006',query_id:queryFixture().id,status:'completed',stage:'completed',method_version:'v2',models:{screening:'Flash',evaluation:'Pro'},conditions:{},source_snapshot:{},candidate_count:2,matched_count:0,retryable:false,usage:{model_operations_started:1,succeeded_steps:1,failed_steps:0,pending_steps:0,running_steps:0},steps:[],created_at:'2026-09-08T02:00:00Z'});
export const candidateFixture=(suffix=1):CandidateView=>({id:`20000000-0000-4000-8000-${String(suffix).padStart(12,'0')}`,creator_id:`30000000-0000-4000-8000-${String(suffix).padStart(12,'0')}`,platform:'youtube',account_id:`UC_${suffix}`,account:{display_name:`Creator ${suffix}`,follower_count:12000,country:'US',languages:['en']},creator:{...creatorFixture(`Creator ${suffix}`),id:`30000000-0000-4000-8000-${String(suffix).padStart(12,'0')}`},filter_notes:{},identity_revision:1,identity_changed:false,added_at:'2026-09-08T01:00:00Z',selected:false});
export function matchAPIMock():MatchAPI {return {
  activities:vi.fn(async()=>ok({items:[activityFixture()],total:1,offset:0,limit:50})),
  activity:vi.fn(async()=>ok({...activityFixture(),queries:[queryFixture()]})),
  createActivity:vi.fn(async()=>ok(activityFixture())),
  plans:vi.fn(async()=>ok({items:[planFixture()],total:1,offset:0,limit:50})),
  createPlan:vi.fn(async()=>ok({plan_id:planFixture().id,status:'queued'})),
  plan:vi.fn(async()=>ok(planFixture())),retryPlan:vi.fn(async()=>ok({plan_id:planFixture().id,status:'queued'})),
  query:vi.fn(async()=>ok(queryFixture())),candidates:vi.fn(async()=>ok({items:[candidateFixture(1),candidateFixture(2)],total:2,limit:100,offset:0})),
  stop:vi.fn(async()=>ok({query_id:queryFixture().id,status:'stopped',stop_requested:true})),
  continueDiscovery:vi.fn(async()=>ok({query_id:queryFixture().id,batch_id:'10000000-0000-4000-8000-000000000005',status:'queued'})),
  evaluations:vi.fn(async()=>ok({items:[],total:0,limit:50,offset:0})),
  evaluate:vi.fn(async()=>ok({evaluation_id:evaluationFixture().id,status:'queued'})),
  evaluation:vi.fn(async()=>ok(evaluationFixture())),evaluationResults:vi.fn(async()=>ok({items:[],total:0,limit:100,offset:0})),
  retryEvaluation:vi.fn(async()=>ok({evaluation_id:evaluationFixture().id,status:'queued'})),
};}
