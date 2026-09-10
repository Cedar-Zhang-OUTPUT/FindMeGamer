import {useState,type ReactNode} from 'react';
import type {CreatorSearch,CreatorSearchPerson} from '../../../shared/creatorSearch';
import type {CandidateView,EvaluationResult} from '../../../shared/match';
import type {PublicError} from '../../../shared/bridge';
import {ErrorNotice,Loading,friendlyLabel} from '../Primitives';
import {creatorSearchRunning} from './useCreatorSearchSession';
import {platformLabel,taskLabel} from './matchStatus';
const stages={planning:'Planning your search',discovery:'Finding creators',profiles:'Preparing creator profiles',emails:'Finding contact details',screening:'Checking audience fit',deep_match:'Evaluating matches',ranking:'Organizing results',complete:'Organizing results'};
const emails={pending:'Email pending',running:'Finding email',available:'Email available',missing:'Email not found',failed:'Email lookup failed'};
interface Props {
 search:CreatorSearch|null;loading:boolean;current:boolean;people:CreatorSearchPerson[];results:EvaluationResult[];candidates:CandidateView[];error:PublicError|null;disabled:boolean;selectionDisabled?:boolean;
 onStop:()=>void;onRetry:(acknowledge:boolean)=>void;onAppend:()=>void;onRefresh:()=>void;onOpenCreator:(id:string,section?:'overview'|'contacts'|'works')=>void;onOpenExternal:(url:string)=>void;
 isSelected:(candidate:CandidateView)=>boolean;onToggle:(candidate:CandidateView)=>void;children?:ReactNode;
}
export function CreatorSearchView({search,loading,current,people,results,candidates,error,disabled,selectionDisabled,onStop,onRetry,onAppend,onRefresh,onOpenCreator,onOpenExternal,isSelected,onToggle,children}:Props){
 const [acknowledged,setAcknowledged]=useState(false);
 if(!search)return <section aria-label="Creator search">{error?<ErrorNotice error={error} onRetry={onRefresh}/>:<Loading label="Loading creator search…"/>}</section>;
 const running=creatorSearchRunning(search),c=search.counts;
 const title=running?stages[search.stage]:search.status==='completed'?'Complete':search.status==='partial'?'Finished with issues':search.status==='stopped'?'Search stopped':'Search could not finish';
 const processed=search.stage==='profiles'?c.profile_ready+c.profile_failed:search.stage==='emails'?c.email_available+c.email_missing+c.email_failed:c.evaluated;
 const matched=new Map(results.map(row=>[row.candidate_id,row])),members=new Map(candidates.map(row=>[row.id,row]));
 const ordered=[...results.map(row=>row.candidate_id),...people.filter(row=>!matched.has(row.candidate_id)).map(row=>row.candidate_id)];
 return <section className="creator-search" aria-label="Creator search">
   <header className="creator-search-progress"><div><h2>{title}</h2><p role="status">{running&&['planning','discovery'].includes(search.stage)?`${c.discovered} creators found`:`${processed} processed · ${c.discovered} discovered`}{!running?` · ${c.matched} matched`:''}</p></div>
     {running?<button className="button secondary" disabled={disabled||search.stop_requested} onClick={onStop}>{search.stop_requested?'Stopping…':'Stop search'}</button>:search.query_id&&<button className="button secondary" disabled={disabled||!current} onClick={onAppend}>Find more creators</button>}
   </header>
   {search.error_code&&<p className="inline-warning" role="status">{taskLabel(search.error_code)}</p>}
   {search.retryable&&!running&&<div className="creator-search-retry">{search.outcome_unknown&&<label><input type="checkbox" checked={acknowledged} onChange={event=>setAcknowledged(event.target.checked)}/>I accept possible repeated provider or model charges</label>}<button className="button secondary" disabled={disabled||(search.outcome_unknown&&!acknowledged)} onClick={()=>{onRetry(acknowledged);setAcknowledged(false);}}>Retry unfinished work</button></div>}
   {error&&<ErrorNotice error={error} onRetry={onRefresh}/>}
   <details className="match-context creator-search-details"><summary>Processing details</summary><dl>{Object.entries(c).map(([key,value])=><div key={key}><dt>{friendlyLabel(key)}</dt><dd>{value}</dd></div>)}</dl>{children}
     {people.some(person=>person.profile_error_code||person.email_error_code)&&<ul>{people.filter(person=>person.profile_error_code||person.email_error_code).map(person=><li key={person.candidate_id}><button className="text-button" onClick={()=>onOpenCreator(person.creator_id)}>{members.get(person.candidate_id)?.creator?.name||person.platform}</button> · {taskLabel(person.profile_error_code||person.email_error_code||'failed')}</li>)}</ul>}
   </details>
   {!running&&!current&&loading&&<Loading label="Loading organized results…"/>}
   {!running&&(current||ordered.length>0)&&<section className="match-results creator-search-results" aria-label="Creator matches">
     {!current&&<p role="status">Showing previously loaded results. Refresh before changing the selection.</p>}
     {!ordered.length?<p>No creators to review.</p>:<ul className="match-result-list">{ordered.map(id=>{const result=matched.get(id),candidate=members.get(id),person=people.find(row=>row.candidate_id===id),creatorId=result?.creator_id||person?.creator_id;
       if(!creatorId)return null;const name=result?.name||candidate?.creator?.name||candidate?.account_id||'Creator';const stale=Boolean(result?.stale||result?.identity_changed||candidate?.identity_changed);
       return <li key={id}><article className="match-card creator-search-card" aria-label={name}><header><div className="creator-search-person">{candidate&&<input type="checkbox" aria-label={`Select ${name}`} disabled={disabled||selectionDisabled||!current||stale} checked={isSelected(candidate)} onChange={()=>onToggle(candidate)}/>}<div><span className="eyebrow">{platformLabel(result?.platform||person?.platform||'')}</span><h3>{name}</h3></div></div><div className="match-card-badges"><span className={`match-badge fit ${result?.fit_group??'unranked'}`}>{result?friendlyLabel(result.fit_group):'Not evaluated'}</span><span className={`match-badge ${person?.email_status==='available'?'neutral':'warning'}`}>{person?emails[person.email_status]:'Email status unavailable'}</span>{stale&&<span className="match-badge warning">Needs refresh</span>}</div><button className="text-button" onClick={()=>onOpenCreator(creatorId)}>View {name}</button></header>
       {result?.match_brief&&<p className="match-summary">{result.match_brief.summary}</p>}
       {result?.evidence.length? <div className="creator-search-works"><strong>Related works</strong><ul>{result.evidence.slice(0,2).map(work=><li key={work.work_id}>{work.content_title||'Work record'}{work.source_url?.startsWith('https://')&&<button className="text-button" onClick={()=>onOpenExternal(work.source_url!)}>View source</button>}</li>)}</ul></div>:<button className="text-button" onClick={()=>onOpenCreator(creatorId,'works')}>View known works</button>}
       {result?.match_brief&&<details className="match-details"><summary>Match details</summary><p>{result.match_brief.content_fit}</p><p>{result.match_brief.audience_fit}</p>{result.match_brief.limitations.length>0&&<ul>{result.match_brief.limitations.map((item,index)=><li key={index}>{item}</li>)}</ul>}</details>}
       </article></li>;
     })}</ul>}
   </section>}
 </section>;
}
