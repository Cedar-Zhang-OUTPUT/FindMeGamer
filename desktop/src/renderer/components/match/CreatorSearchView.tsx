import {useState,type ReactNode} from 'react';
import type {CreatorSearch,CreatorSearchPerson} from '../../../shared/creatorSearch';
import type {CandidateView,EvaluationResult} from '../../../shared/match';
import type {PublicError} from '../../../shared/bridge';
import {ErrorNotice,Loading,friendlyLabel} from '../Primitives';
import {creatorSearchRunning,type SearchReadErrors} from './useCreatorSearchSession';
import {platformLabel,taskLabel} from './matchStatus';
import './reviewTable.css';
import {SelectionActions} from '../SelectionActions';
const stages={planning:'Planning your search',discovery:'Finding creators',profiles:'Preparing creator profiles',emails:'Finding contact details',screening:'Checking audience fit',deep_match:'Evaluating matches',ranking:'Organizing results',complete:'Organizing results'};
const emails={pending:'Email pending',running:'Finding email',available:'Email available',missing:'Email not found',failed:'Email lookup failed'};
interface Props {
 search:CreatorSearch|null;loading:boolean;current:boolean;people:CreatorSearchPerson[];results:EvaluationResult[];candidates:CandidateView[];error:PublicError|null;readErrors?:SearchReadErrors;disabled:boolean;selectionDisabled?:boolean;
 onStop:()=>void;onRetry:(acknowledge:boolean)=>void;onAppend:()=>void;onRefresh:()=>void;onOpenCreator:(id:string,section?:'overview'|'contacts'|'works')=>void;onOpenExternal:(url:string)=>void;
 isSelected:(candidate:CandidateView)=>boolean;onToggle:(candidate:CandidateView)=>void;onSetLoaded?:(rows:CandidateView[],selected:boolean)=>void;children?:ReactNode;
}
export function CreatorSearchView({search,loading,current,people,results,candidates,error,readErrors={},disabled,selectionDisabled,onStop,onRetry,onAppend,onRefresh,onOpenCreator,onOpenExternal,isSelected,onToggle,onSetLoaded,children}:Props){
 const [acknowledged,setAcknowledged]=useState(false);
 if(!search)return <section aria-label="Creator search">{error?<ErrorNotice error={error} onRetry={onRefresh}/>:<Loading label="Loading creator search…"/>}</section>;
 const running=creatorSearchRunning(search),c=search.counts;
 const title=running?stages[search.stage]:search.status==='completed'?'Complete':search.status==='partial'?'Finished with issues':search.status==='stopped'?'Search stopped':'Search could not finish';
 const processed=search.stage==='profiles'?c.profile_ready+c.profile_failed:search.stage==='emails'?c.email_available+c.email_missing+c.email_failed:c.evaluated;
 const matched=new Map(results.map(row=>[row.candidate_id,row])),members=new Map(candidates.map(row=>[row.id,row]));
 const selectable=candidates.filter(row=>!row.identity_changed&&!matched.get(row.id)?.stale&&!matched.get(row.id)?.identity_changed&&(matched.has(row.id)||people.some(person=>person.candidate_id===row.id)));
 const ordered=[...results.map(row=>row.candidate_id),...people.filter(row=>!matched.has(row.candidate_id)).map(row=>row.candidate_id)];
 return <section className="creator-search" aria-label="Creator search">
   <header className="creator-search-progress"><div><h2>{title}</h2><p role="status">{running&&['planning','discovery'].includes(search.stage)?`${c.discovered} creators found`:`${processed} processed · ${c.discovered} discovered`}{!running?` · ${c.matched} matched`:''}</p></div>
     {running?<button className="button secondary" disabled={disabled||search.stop_requested} onClick={onStop}>{search.stop_requested?'Stopping…':'Stop search'}</button>:search.query_id&&<button className="button secondary" disabled={disabled||!current} onClick={onAppend}>Find more creators</button>}
   </header>
   {search.error_code&&<p className="inline-warning" role="status">{taskLabel(search.error_code)}</p>}
   {search.retryable&&!running&&<div className="creator-search-retry">{search.outcome_unknown&&<label><input type="checkbox" checked={acknowledged} onChange={event=>setAcknowledged(event.target.checked)}/>I accept possible repeated provider or model charges</label>}<button className="button secondary" disabled={disabled||(search.outcome_unknown&&!acknowledged)} onClick={()=>{onRetry(acknowledged);setAcknowledged(false);}}>Retry unfinished work</button></div>}
   {error&&<ErrorNotice error={error} onRetry={onRefresh}/>}
   {Object.keys(readErrors).length>0&&<section aria-label="Result loading issues">
     {(['results','people','candidates'] as const).map(key=>readErrors[key]&&<div key={key}><h3>{ {results:'Match details',people:'Profiles & email status',candidates:'Selection data'}[key]}</h3><ErrorNotice error={readErrors[key]!}/></div>)}
     <button className="button secondary" disabled={loading} onClick={onRefresh}>{loading?'Reloading results…':'Reload results'}</button>
   </section>}
   <details className="match-context creator-search-details"><summary>Processing details</summary><dl>{Object.entries(c).map(([key,value])=><div key={key}><dt>{friendlyLabel(key)}</dt><dd>{value}</dd></div>)}</dl>{children}
     {people.some(person=>person.profile_error_code||person.email_error_code)&&<ul>{people.filter(person=>person.profile_error_code||person.email_error_code).map(person=><li key={person.candidate_id}><button className="text-button" onClick={()=>onOpenCreator(person.creator_id)}>{members.get(person.candidate_id)?.creator?.name||person.platform}</button> · {taskLabel(person.profile_error_code||person.email_error_code||'failed')}</li>)}</ul>}
   </details>
   {!running&&!current&&loading&&<Loading label="Loading organized results…"/>}
   {!running&&(current||ordered.length>0)&&<section className="match-results creator-search-results" aria-label="Creator matches">
     {!current&&<p role="status">Partial or saved results · Selection unavailable until reload completes.</p>}
     {onSetLoaded&&<SelectionActions scope="Loaded creators" count={selectable.length} selected={selectable.filter(isSelected).length} disabled={disabled||selectionDisabled||!current} onSelect={()=>onSetLoaded(selectable,true)} onClear={()=>onSetLoaded(selectable,false)}/>}
     {!ordered.length?<p>No creators to review.</p>:<div className="review-table-scroll" tabIndex={0} role="region" aria-label="Scrollable match results"><table className="review-table" aria-label="Creator matches"><thead><tr>{['Select','Creator','Platform','Recorded work','Match','Email','Languages','Details'].map(label=><th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{ordered.map(id=>{const result=matched.get(id),candidate=members.get(id),person=people.find(row=>row.candidate_id===id),creatorId=result?.creator_id||person?.creator_id||candidate?.creator_id;
       if(!creatorId)return null;const name=result?.name||candidate?.creator?.name||candidate?.account_id||'Creator';const stale=Boolean(result?.stale||result?.identity_changed||candidate?.identity_changed);
       return <tr key={id} data-candidate-id={id}>
         <td>{candidate?<input type="checkbox" aria-label={`Select ${name}`} disabled={disabled||selectionDisabled||!current||stale} checked={isSelected(candidate)} onChange={()=>onToggle(candidate)}/>:<span className="review-table-muted">Unavailable</span>}</td>
         <th scope="row"><button className="text-button review-person" aria-label={`View ${name}`} onClick={()=>onOpenCreator(creatorId)}>{name}</button>{stale&&<span className="review-table-muted">Needs refresh</span>}</th>
         <td>{platformLabel(result?.platform||person?.platform||candidate?.platform||'')}</td>
         <td><span>{result?.evidence[0]?.content_title||'Not recorded'}</span>{!!result?.evidence.length&&result.evidence.length>1&&<span className="review-table-muted">+{result.evidence.length-1} works</span>}<button className="text-button" onClick={()=>onOpenCreator(creatorId,'works')}>View known works</button></td>
         <td><span className={`match-badge fit ${result?.fit_group??'unranked'}`}>{result?friendlyLabel(result.fit_group):current?'Not evaluated':'Match details unavailable'}</span></td>
         <td><span className={`match-badge ${person?.email_status==='available'?'neutral':'warning'}`}>{person?emails[person.email_status]:'Email status unavailable'}</span></td>
         <td>{candidate?.creator?.languages.length?candidate.creator.languages.join(', '):'Unknown'}</td>
         <td>{result?<details className="review-row-details"><summary aria-label={`Match details for ${name}`}>Match details</summary>{result.match_brief&&<><p>{result.match_brief.summary}</p><p>{result.match_brief.content_fit}</p><p>{result.match_brief.audience_fit}</p>{result.match_brief.limitations.length>0&&<ul>{result.match_brief.limitations.map((item,index)=><li key={index}>{item}</li>)}</ul>}</>}{result.evidence.length>0&&<ul>{result.evidence.map(work=><li key={work.work_id}>{work.content_title||'Work record'}{work.source_url?.startsWith('https://')&&<button className="text-button" onClick={()=>onOpenExternal(work.source_url!)}>View source</button>}</li>)}</ul>}</details>:<span className="review-table-muted">Not available</span>}</td>
       </tr>;
     })}</tbody></table></div>}
   </section>}
 </section>;
}
