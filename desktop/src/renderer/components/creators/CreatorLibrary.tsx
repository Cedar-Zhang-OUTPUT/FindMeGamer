import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import type { CreatorDetail, CreatorListInput, CreatorPage, CreatorPlatform, CreatorSort } from '../../../shared/creators';
import type { NavigationGuard } from '../../../shared/games';
import { analyzedDate, EmptyState, ErrorNotice, Icon, Loading } from '../Primitives';
import { CreatorRecord, type CreatorRecordProps } from './CreatorRecord';
import { CreatorEditor } from './CreatorEditor';
import { CreatorIdentityEditor } from './CreatorIdentityEditor';
import type { EditContext } from './creatorDraft';
import { LanguageFilter, PlatformFilter } from './CreatorLibraryFilters';
import './creatorLibrary.css';
import '../match/reviewTable.css';
import {useAnalyze} from '../analyze/AnalyzeProvider';
import {SourceImport} from '../analyze/SourceImport';

type Section = 'profile' | 'emails' | 'works';
type Intent='detail'|'edit'|'works'|'emails';
type Route = {kind:'list'} | {kind:'loading'; id:string; error:PublicError|null;intent:Intent} | {kind:'detail'; creator:CreatorDetail; section:Section; saved?:boolean} | {kind:'editor'; initial:EditContext; creator:CreatorDetail|null; section:Section;returnToList?:boolean} | {kind:'identity'; creator:CreatorDetail} | {kind:'source';creator:CreatorDetail};
type Filters = {query:string; platforms:CreatorPlatform[]; languages:string[]; sort:CreatorSort; onlyCollection:boolean};
const emptyFilters:Filters = {query:'',platforms:[],languages:[],sort:'relevance',onlyCollection:false};
const networkError:PublicError = {code:'network_error',message:'Creators could not be loaded. Your current page is still here.',retryable:true};
const platformNames = {youtube:'YouTube',x:'X',twitch:'Twitch',instagram:'Instagram'};
const nameOf = (creator:CreatorDetail) => creator.name || creator.public_name || creator.handle || creator.source_identity.account_id || 'Unnamed creator';
function inputFor(filters:Filters,offset=0):CreatorListInput { return {query:filters.query,platforms:[...filters.platforms],languages:[...filters.languages],sort:filters.sort,onlyCollection:filters.onlyCollection,offset,limit:50}; }
function filtersFor(input:CreatorListInput):Filters { return {query:input.query??'',platforms:[...(input.platforms??(input.platform?[input.platform]:[]))],languages:[...(input.languages??(input.language?[input.language]:[]))],sort:input.sort??'relevance',onlyCollection:input.onlyCollection??false}; }
const recentTitles=(creator:CreatorDetail)=>creator.recent_works?.map(work=>work.work_name||work.content_title).filter((title):title is string=>Boolean(title)).join(' · ');
function emailSummary(creator:CreatorDetail){
  if(creator.contact_status==='missing')return 'No active email';
  if(creator.contact_status==='available'&&creator.active_email_count!==undefined)return `${creator.active_email_count} active email${creator.active_email_count===1?'':'s'}`;
  if(creator.contact_status==='available')return 'Active email available';
  return 'Email availability unknown';
}

export function CreatorLibrary({api,active,onNavigationGuardChange,onConnectionRepair,openRequest,onViewChange}:{api:DesktopBridge;active:boolean;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void;openRequest?:{id:string;nonce:number};onViewChange?:(view:'list'|'record')=>void}) {
  const analyze=useAnalyze();
  const [filters,setFilters]=useState<Filters>(emptyFilters);
  const [desiredFilters,setDesiredFilters]=useState<Filters>(emptyFilters);
  const [search,setSearch]=useState('');
  const [page,setPage]=useState<CreatorPage|null>(null),[busy,setBusy]=useState(false);
  const [error,setError]=useState<PublicError|null>(null),[failedInput,setFailedInput]=useState<CreatorListInput|null>(null);
  const [route,setRoute]=useState<Route>({kind:'list'});
  useLayoutEffect(()=>{onViewChange?.(route.kind==='list'?'list':'record');},[route.kind,onViewChange]);
  const alive=useRef(true),loaded=useRef(false),generation=useRef(0),detailGeneration=useRef(0);
  const listRoot=useRef<HTMLDivElement>(null),listScroll=useRef(0),selectedId=useRef<string|null>(null);
  const restoreFrame=useRef<number|null>(null);
  useLayoutEffect(()=>()=>{if(restoreFrame.current!==null){cancelAnimationFrame(restoreFrame.current);restoreFrame.current=null;}},[active]);
  const current=useRef({filters:desiredFilters,page});current.current={filters:desiredFilters,page};
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;loaded.current=false;generation.current++;detailGeneration.current++;};},[]);
  useEffect(()=>()=>onNavigationGuardChange?.(null),[onNavigationGuardChange]);
  const loadPage=useCallback(async(input:CreatorListInput)=>{
    const request={...input,limit:50,offset:input.offset??0};const token=++generation.current;
    setDesiredFilters(filtersFor(request));setBusy(true);setError(null);setFailedInput(null);
    try {
      const result=await api.creators.list(request);
      if(!alive.current||token!==generation.current)return;
      if(!result.ok){setError(result.error);setFailedInput(request);setBusy(false);return;}
      const lastOffset=Math.max(0,Math.floor((result.data.total-1)/50)*50);
      if(request.offset>lastOffset){void loadPage({...request,offset:lastOffset});return;}
      setFilters(filtersFor(request));setPage(result.data);setBusy(false);
    } catch {if(alive.current&&token===generation.current){setError(networkError);setFailedInput(request);setBusy(false);}}
  },[api]);
  useEffect(()=>{if(active&&!loaded.current){loaded.current=true;void loadPage(inputFor(emptyFilters));}},[active,loadPage]);
  useEffect(()=>{if(openRequest)void open(openRequest.id);},[openRequest]);
  function rememberScroll(){listScroll.current=document.querySelector<HTMLElement>('.main-scroll')?.scrollTop??0;}
  function scrollTop(){const scroller=document.querySelector<HTMLElement>('.main-scroll');if(scroller)scroller.scrollTop=0;}
  function back(){detailGeneration.current++;setRoute({kind:'list'});if(restoreFrame.current!==null)cancelAnimationFrame(restoreFrame.current);restoreFrame.current=requestAnimationFrame(()=>{
    restoreFrame.current=null;
    if(!listRoot.current||listRoot.current.closest('[hidden]'))return;
    const scroller=document.querySelector<HTMLElement>('.main-scroll');if(scroller)scroller.scrollTop=listScroll.current;
    const row=Array.from(listRoot.current?.querySelectorAll<HTMLButtonElement>('[data-creator-id]')??[]).find(node=>node.dataset.creatorId===selectedId.current);
    (row??listRoot.current?.querySelector<HTMLInputElement>('input[type="search"]'))?.focus({preventScroll:true});
  });}
  async function open(id:string,retry=false,intent:Intent='detail'){
    if(!retry){rememberScroll();selectedId.current=id;scrollTop();}const token=++detailGeneration.current;setRoute({kind:'loading',id,error:null,intent});
    try {const result=await api.creators.detail(id);if(!alive.current||token!==detailGeneration.current)return;
      setRoute(result.ok?(intent==='edit'?{kind:'editor',creator:result.data,section:'profile',initial:{kind:'creator',base:result.data},returnToList:true}:{kind:'detail',creator:result.data,section:intent==='works'?'works':intent==='emails'?'emails':'profile'}):{kind:'loading',id,error:result.error,intent});
    }catch{if(alive.current&&token===detailGeneration.current)setRoute({kind:'loading',id,error:networkError,intent});}
  }
  function edit(target:Parameters<CreatorRecordProps['onEdit']>[0]){
    if(route.kind!=='detail')return;
    if(target.kind==='identity'){setRoute({kind:'identity',creator:route.creator});return;}
    setRoute({kind:'editor',creator:route.creator,section:target.kind==='contact'?'emails':target.kind==='work'?'works':'profile',initial:target.kind==='creator'?{kind:'creator',base:route.creator}:{kind:target.kind,base:target.base??null,creator:route.creator}});
  }
  function cancel(){if(route.kind==='editor'&&route.returnToList)back();else if(route.kind==='editor'&&route.creator)setRoute({kind:'detail',creator:route.creator,section:route.section});else if(route.kind==='identity')setRoute({kind:'detail',creator:route.creator,section:'profile'});else back();}
  function saved(creator:CreatorDetail){
    detailGeneration.current++;selectedId.current=creator.id;setRoute({kind:'detail',creator,section:route.kind==='editor'?route.section:'profile',saved:true});scrollTop();
    setPage(previous=>previous?{...previous,items:previous.items.map(item=>item.id===creator.id?creator:item)}:null);
    void loadPage(inputFor(current.current.filters,current.current.page?.offset??0));
  }
  function clear(){setSearch('');void loadPage(inputFor(emptyFilters));}
  const filtered=Boolean(filters.query||filters.platforms.length||filters.languages.length||filters.onlyCollection||filters.sort!=='relevance');
  const selected=route.kind==='detail'?route.creator:null;
  const identity=selected?.source_identity;
  const analyzeAllowed=Boolean(selected?.analysis_available&&identity?.account_id&&identity.canonical_url&&(identity.platform==='youtube'&&/^https:\/\/(www\.)?youtube\.com\/channel\/UC[A-Za-z0-9_-]+\/?$/.test(identity.canonical_url)||identity.platform==='x'&&/^\d+$/.test(identity.account_id)&&identity.canonical_url===`https://x.com/i/user/${identity.account_id}`));
  return <div className="creator-library">
    <div ref={listRoot} hidden={route.kind!=='list'}>
      <div className="creator-library-tools"><form className="search-form" role="search" onSubmit={event=>{event.preventDefault();void loadPage(inputFor({...desiredFilters,query:search.trim()},0));}}><Icon name="search"/><input type="search" aria-label="Search creators" placeholder="Search creators…" maxLength={255} value={search} onChange={event=>setSearch(event.target.value)}/><button className="button primary" type="submit">Search</button></form><button className="button primary" onClick={()=>{rememberScroll();scrollTop();setRoute({kind:'editor',initial:{kind:'creator',base:null},creator:null,section:'profile'});}}>New creator</button></div>
      <div className="creator-library-filters"><PlatformFilter value={desiredFilters.platforms} onApply={platforms=>void loadPage(inputFor({...desiredFilters,platforms},0))}/><LanguageFilter value={desiredFilters.languages} onApply={languages=>void loadPage(inputFor({...desiredFilters,languages},0))}/><label className="creator-sort">Sort creators<select aria-label="Sort creators" value={desiredFilters.sort} onChange={event=>void loadPage(inputFor({...desiredFilters,sort:event.target.value as CreatorSort},0))}><option value="relevance">Search relevance</option><option value="followers">Follower count</option><option value="recent_publish">Recently published</option><option value="recent_added">Recently added</option></select></label><label className="collection-filter"><input type="checkbox" checked={desiredFilters.onlyCollection} onChange={event=>void loadPage(inputFor({...desiredFilters,onlyCollection:event.target.checked},0))}/><Icon name="collection"/>Saved only</label><button className="icon-button" aria-label="Refresh Library" title="Refresh Library" disabled={busy} onClick={()=>void loadPage(failedInput??inputFor(desiredFilters,page?.offset??0))}><Icon name="refresh"/></button></div>
      {filtered&&<div className="active-filters"><span>{[filters.query&&`Results for “${filters.query}”`,filters.platforms.length&&`${filters.platforms.length} platform${filters.platforms.length===1?'':'s'}`,filters.languages.length&&`${filters.languages.length} language${filters.languages.length===1?'':'s'}`,filters.sort!=='relevance'&&`Ordered by ${filters.sort.replaceAll('_',' ')}`,filters.onlyCollection&&'Saved profiles'].filter(Boolean).join(' · ')}</span><button className="text-button" onClick={clear}>Clear filters<Icon name="close"/></button></div>}
      {busy&&<Loading label="Loading creators…"/>}
      {page&&(busy||error)&&<p className="muted" role="status">Previous results</p>}
      {page&&<><div className="list-caption"><span>{page.items.length?page.offset+1:0}–{page.items.length?page.offset+page.items.length:0} of {page.total}</span></div><div className="review-table-scroll" tabIndex={0} role="region" aria-label="Scrollable creators"><table className="review-table" aria-label="Creators"><thead><tr>{['Creator','Platform','Recent work','Contact','Updated','Actions'].map(title=><th scope="col" key={title}>{title}</th>)}</tr></thead><tbody>{page.items.map(creator=><tr key={creator.id}><th scope="row"><button className="text-button review-person" data-creator-id={creator.id} aria-label={`Open ${nameOf(creator)}`} onClick={()=>void open(creator.id)}>{nameOf(creator)}{creator.favorite&&<Icon name="collection"/>}</button><span className="review-table-muted">{creator.follower_count===null?'Followers unknown':`${new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(creator.follower_count)} followers`}</span></th><td>{platformNames[creator.source_identity.platform]}<span className="review-table-muted">{creator.languages.length?creator.languages.join(', '):'Languages unknown'}</span>{(creator.source_identity.platform==='twitch'||creator.source_identity.platform==='instagram')&&<span className="review-table-muted">Manual · discovery unavailable</span>}</td><td>{recentTitles(creator)||'Not recorded'}<button className="text-button" aria-label={`View works for ${nameOf(creator)}`} onClick={()=>void open(creator.id,false,'works')}>View works</button></td><td>{emailSummary(creator)}<button className="text-button" aria-label={`View contacts for ${nameOf(creator)}`} onClick={()=>void open(creator.id,false,'emails')}>View contacts</button></td><td>{analyzedDate(creator.updated_at??null)}</td><td><button className="text-button" aria-label={`Edit ${nameOf(creator)}`} onClick={()=>void open(creator.id,false,'edit')}>Edit</button></td></tr>)}</tbody></table></div></>}
      {error&&<ErrorNotice error={error} onRetry={failedInput?()=>void loadPage(failedInput):undefined}/>}
      {!busy&&!error&&page?.items.length===0&&<EmptyState title={filtered?'No matching profiles':'No creators yet'} action={filtered?<button className="button secondary" onClick={clear}>Clear filters</button>:undefined}/>}
      {page&&page.total>0&&<div className="creator-library-pagination"><button className="button secondary" disabled={busy||Boolean(error)||page.offset===0} onClick={()=>void loadPage(inputFor(desiredFilters,Math.max(0,page.offset-50)))}>Previous page</button><button className="button secondary" disabled={busy||Boolean(error)||page.offset+page.limit>=page.total} onClick={()=>void loadPage(inputFor(desiredFilters,page.offset+page.limit))}>Next page</button></div>}
    </div>
    {route.kind==='loading'&&<><button className="text-button back-button" onClick={back}><Icon name="arrow"/>Back to creators</button>{route.error?<ErrorNotice error={route.error} onRetry={()=>void open(route.id,true,route.intent)}/>:<Loading label="Loading creator…"/>}</>}
    {route.kind==='detail'&&<>{route.saved&&<div className="creator-saved-message" role="status"><Icon name="check"/>Saved</div>}<CreatorRecord key={route.creator.id} api={api} creator={route.creator} initialSection={route.section} refreshToken={route.creator.revision} onBack={back} onEdit={edit} onAnalyze={analyzeAllowed?()=>analyze.request({target_type:'creator',url:route.creator.source_identity.canonical_url!,mode:'reanalyze',profileId:route.creator.id,title:nameOf(route.creator)}):undefined} onBindYouTube={identity?.platform==='youtube'&&!identity.account_id?()=>setRoute({kind:'source',creator:route.creator}):undefined}/>{identity?.platform==='x'&&!identity.account_id&&<p className="muted">Analyze requires a bound numeric X account.</p>}{(identity?.platform==='twitch'||identity?.platform==='instagram')&&<p className="muted">Analyze is not connected for this platform.</p>}</>}
    {route.kind==='source'&&<SourceImport api={api} target={{kind:'youtube',creator:route.creator}} onSaved={record=>saved(record as CreatorDetail)} onClose={()=>{onNavigationGuardChange?.(null);setRoute({kind:'detail',creator:route.creator,section:'profile'});}} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/>}
    {route.kind==='editor'&&<CreatorEditor api={api} initial={route.initial} onSaved={saved} onCancel={cancel} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/>}
    {route.kind==='identity'&&<CreatorIdentityEditor api={api} initial={route.creator} onSaved={saved} onCancel={cancel} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/>}
  </div>;
}
