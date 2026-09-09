import {useEffect,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {JsonObject,JsonValue} from '../../../shared/library';
import {ErrorNotice,friendlyLabel} from '../Primitives';
import './sourceImport.css';
function object(value:JsonValue|undefined):JsonObject|undefined{return value&&typeof value==='object'&&!Array.isArray(value)?value:undefined;}
function text(value:JsonValue|undefined):string|null{return typeof value==='string'?value:typeof value==='number'?String(value):Array.isArray(value)&&value.every(x=>typeof x==='string')?value.join(' · '):null;}
function observations(data:JsonObject){return Object.entries(data).flatMap(([key,value])=>{const item=object(value);const content=item?.status==='available'?text(item.value??item.text??item.values):null;return content?[{key,content,item:item!}]:[];});}
function Evidence({item}:{item:JsonObject}){return <details className="insight-evidence"><summary>Evidence</summary>{text(item.confidence)&&<p>Confidence: {text(item.confidence)}</p>}{Array.isArray(item.cited_source_ids)&&<p>Source IDs: {text(item.cited_source_ids)}</p>}{Array.isArray(item.evidence)&&<ul>{item.evidence.map((value,index)=>{const e=object(value);return e?<li key={index}>{text(e.observation)}<span className="muted">{text(e.source_type)} · {text(e.reference??e.source_id)}</span></li>:null;})}</ul>}</details>;}
export function AnalysisInsights({brief={},analysis={},sourceStatus={}}:{brief?:JsonObject;analysis?:JsonObject;sourceStatus?:JsonObject}){
 const seen=new Set<string>(),all=[...observations(brief),...observations(analysis)].filter(item=>{if(seen.has(item.content))return false;seen.add(item.content);return true;}),primary=all.slice(0,3),secondary=all.slice(3);
 if(!Object.keys(brief).length&&!Object.keys(analysis).length&&!Object.keys(sourceStatus).length)return null;
 return <section className="analysis-insights" aria-label="Analysis insights"><header><span className="eyebrow">AI interpretation</span><h2>At a glance</h2>{sourceStatus.freshness==='stale'&&<span className="status-badge">Previous analysis · stale</span>}</header>
 {sourceStatus.coverage==='recent_account_posts'&&<p className="analysis-coverage">{typeof sourceStatus.sample_size==='number'?`${sourceStatus.sample_size} recent original posts`:'Recent original posts'} · One page{typeof sourceStatus.post_limit==='number'?` · Up to ${sourceStatus.post_limit}`:''}{sourceStatus.more_available===true?' · More posts available':''}</p>}
 {primary.length?<div className="insight-grid">{primary.map(({key,content,item})=><article key={key}><h3>{friendlyLabel(key)}</h3><p>{content}</p><Evidence item={item}/></article>)}</div>:<p className="muted">No supported interpretation yet.</p>}
 {secondary.length>0&&<details className="analysis-more"><summary>More analysis · {secondary.length}</summary>{secondary.map(({key,content,item})=><article key={key}><h3>{friendlyLabel(key)}</h3><p>{content}</p><Evidence item={item}/></article>)}</details>}
 <details className="analysis-more"><summary>Coverage &amp; unavailable fields</summary><dl>{Object.entries(sourceStatus).filter(([,v])=>text(v)!==null).map(([k,v])=><div key={k}><dt>{friendlyLabel(k)}</dt><dd>{text(v)}</dd></div>)}</dl>{[...Object.entries(brief),...Object.entries(analysis)].filter(([,v])=>object(v)?.status==='unavailable').map(([k,v],i)=><p key={`${k}-${i}`}><strong>{friendlyLabel(k)}</strong> · {text(object(v)?.reason)??'Unavailable'}</p>)}</details>
 </section>;
}
export function GameAnalysisInsights({api,id,revision}:{api:DesktopBridge;id:string;revision:number}){
 const [open,setOpen]=useState(false),[data,setData]=useState<{brief:JsonObject;analysis:JsonObject}|null>(null),[error,setError]=useState<PublicError|null>(null),[attempt,setAttempt]=useState(0);
 useEffect(()=>{if(!open)return;let alive=true;setData(null);setError(null);void api.library.detail({kind:'games',id}).then(result=>{if(!alive)return;if(result.ok)setData({brief:result.data.groups.find(x=>x.id==='brief')?.data??{},analysis:result.data.groups.find(x=>x.id==='analysis')?.data??{}});else setError(result.error);}).catch(()=>{if(alive)setError({code:'network_error',message:'Analysis could not be loaded.',retryable:true});});return()=>{alive=false;};},[api,id,revision,open,attempt]);
 return <details className="analysis-more" onToggle={event=>setOpen(event.currentTarget.open)}><summary>Game analysis</summary>{open&&(data?<AnalysisInsights {...data}/>:error?<ErrorNotice error={error} onRetry={()=>setAttempt(x=>x+1)}/>:<p role="status">Loading analysis…</p>)}</details>;
}
