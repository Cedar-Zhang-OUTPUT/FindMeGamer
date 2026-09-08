import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { DesktopBridge, PublicError } from '../../../shared/bridge';
import { CREATOR_PLATFORMS, type CreatorDetail, type CreatorListInput, type CreatorPage, type CreatorPlatform } from '../../../shared/creators';
import type { NavigationGuard } from '../../../shared/games';
import { analyzedDate, Artwork, EmptyState, ErrorNotice, Icon, Loading } from '../Primitives';
import { CreatorRecord, type CreatorRecordProps } from './CreatorRecord';
import { CreatorEditor } from './CreatorEditor';
import { CreatorIdentityEditor } from './CreatorIdentityEditor';
import type { EditContext } from './creatorDraft';
import './creatorLibrary.css';

type Section = 'profile' | 'emails' | 'works';
type Route = {kind:'list'} | {kind:'loading'; id:string; error:PublicError|null} | {kind:'detail'; creator:CreatorDetail; section:Section; saved?:boolean} | {kind:'editor'; initial:EditContext; creator:CreatorDetail|null; section:Section} | {kind:'identity'; creator:CreatorDetail};
type Filters = {query:string; platform:CreatorPlatform|''; language:string; onlyCollection:boolean};
const emptyFilters:Filters = {query:'',platform:'',language:'',onlyCollection:false};
const networkError:PublicError = {code:'network_error',message:'Creators could not be loaded. Your current page is still here.',retryable:true};
const platformNames = {youtube:'YouTube',x:'X',twitch:'Twitch',instagram:'Instagram'};
const nameOf = (creator:CreatorDetail) => creator.name || creator.public_name || creator.handle || creator.source_identity.account_id || 'Unnamed creator';
function inputFor(filters:Filters,offset=0):CreatorListInput { return {query:filters.query,platform:filters.platform || undefined,language:filters.language || undefined,onlyCollection:filters.onlyCollection,offset,limit:50}; }

export function CreatorLibrary({api,active,onNavigationGuardChange,onConnectionRepair}:{api:DesktopBridge;active:boolean;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void}) {
  const [filters,setFilters]=useState<Filters>(emptyFilters);
  const [search,setSearch]=useState(''),[language,setLanguage]=useState('');
  const [page,setPage]=useState<CreatorPage|null>(null),[busy,setBusy]=useState(false);
  const [error,setError]=useState<PublicError|null>(null),[failedInput,setFailedInput]=useState<CreatorListInput|null>(null);
  const [route,setRoute]=useState<Route>({kind:'list'});
  const alive=useRef(true),loaded=useRef(false),generation=useRef(0),detailGeneration=useRef(0);
  const listRoot=useRef<HTMLDivElement>(null),listScroll=useRef(0),selectedId=useRef<string|null>(null);
  const restoreFrame=useRef<number|null>(null);
  useLayoutEffect(()=>()=>{if(restoreFrame.current!==null){cancelAnimationFrame(restoreFrame.current);restoreFrame.current=null;}},[active]);
  const current=useRef({filters,page});current.current={filters,page};
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;loaded.current=false;generation.current++;detailGeneration.current++;};},[]);
  useEffect(()=>()=>onNavigationGuardChange?.(null),[onNavigationGuardChange]);
  const loadPage=useCallback(async(input:CreatorListInput)=>{
    const request={...input,limit:50,offset:input.offset??0};const token=++generation.current;
    setBusy(true);setError(null);setFailedInput(null);
    setFilters({query:request.query??'',platform:request.platform??'',language:request.language??'',onlyCollection:request.onlyCollection??false});
    try {
      const result=await api.creators.list(request);
      if(!alive.current||token!==generation.current)return;
      if(!result.ok){setError(result.error);setFailedInput(request);setBusy(false);return;}
      const lastOffset=Math.max(0,Math.floor((result.data.total-1)/50)*50);
      if(request.offset>lastOffset){void loadPage({...request,offset:lastOffset});return;}
      setPage(result.data);setBusy(false);
    } catch {if(alive.current&&token===generation.current){setError(networkError);setFailedInput(request);setBusy(false);}}
  },[api]);
  useEffect(()=>{if(active&&!loaded.current){loaded.current=true;void loadPage(inputFor(emptyFilters));}},[active,loadPage]);
  function rememberScroll(){listScroll.current=document.querySelector<HTMLElement>('.main-scroll')?.scrollTop??0;}
  function scrollTop(){const scroller=document.querySelector<HTMLElement>('.main-scroll');if(scroller)scroller.scrollTop=0;}
  function back(){detailGeneration.current++;setRoute({kind:'list'});if(restoreFrame.current!==null)cancelAnimationFrame(restoreFrame.current);restoreFrame.current=requestAnimationFrame(()=>{
    restoreFrame.current=null;
    if(!listRoot.current||listRoot.current.closest('[hidden]'))return;
    const scroller=document.querySelector<HTMLElement>('.main-scroll');if(scroller)scroller.scrollTop=listScroll.current;
    const row=Array.from(listRoot.current?.querySelectorAll<HTMLButtonElement>('[data-creator-id]')??[]).find(node=>node.dataset.creatorId===selectedId.current);
    (row??listRoot.current?.querySelector<HTMLInputElement>('input[type="search"]'))?.focus({preventScroll:true});
  });}
  async function open(id:string,retry=false){
    if(!retry){rememberScroll();selectedId.current=id;scrollTop();}const token=++detailGeneration.current;setRoute({kind:'loading',id,error:null});
    try {const result=await api.creators.detail(id);if(!alive.current||token!==detailGeneration.current)return;
      setRoute(result.ok?{kind:'detail',creator:result.data,section:'profile'}:{kind:'loading',id,error:result.error});
    }catch{if(alive.current&&token===detailGeneration.current)setRoute({kind:'loading',id,error:networkError});}
  }
  function edit(target:Parameters<CreatorRecordProps['onEdit']>[0]){
    if(route.kind!=='detail')return;
    if(target.kind==='identity'){setRoute({kind:'identity',creator:route.creator});return;}
    setRoute({kind:'editor',creator:route.creator,section:target.kind==='contact'?'emails':target.kind==='work'?'works':'profile',initial:target.kind==='creator'?{kind:'creator',base:route.creator}:{kind:target.kind,base:target.base??null,creator:route.creator}});
  }
  function cancel(){if(route.kind==='editor'&&route.creator)setRoute({kind:'detail',creator:route.creator,section:route.section});else if(route.kind==='identity')setRoute({kind:'detail',creator:route.creator,section:'profile'});else back();}
  function saved(creator:CreatorDetail){
    detailGeneration.current++;selectedId.current=creator.id;setRoute({kind:'detail',creator,section:route.kind==='editor'?route.section:'profile',saved:true});scrollTop();
    setPage(previous=>previous?{...previous,items:previous.items.map(item=>item.id===creator.id?creator:item)}:null);
    void loadPage(inputFor(current.current.filters,current.current.page?.offset??0));
  }
  function clear(){setSearch('');setLanguage('');void loadPage(inputFor(emptyFilters));}
  const filtered=Boolean(filters.query||filters.platform||filters.language||filters.onlyCollection);
  return <div className="creator-library">
    <div ref={listRoot} hidden={route.kind!=='list'}>
      <div className="creator-library-tools"><form className="search-form" role="search" onSubmit={event=>{event.preventDefault();void loadPage(inputFor({...filters,query:search.trim(),language:language.trim()}));}}><Icon name="search"/><input type="search" aria-label="Search creators" placeholder="Search creators…" maxLength={255} value={search} onChange={event=>setSearch(event.target.value)}/><button className="button primary" type="submit">Search</button></form><button className="button primary" onClick={()=>{rememberScroll();scrollTop();setRoute({kind:'editor',initial:{kind:'creator',base:null},creator:null,section:'profile'});}}>New creator</button></div>
      <div className="creator-library-filters"><label>Platform<select value={filters.platform} onChange={event=>void loadPage(inputFor({...filters,platform:event.target.value as Filters['platform']}))}><option value="">All platforms</option>{CREATOR_PLATFORMS.map(platform=><option key={platform} value={platform}>{platformNames[platform]}</option>)}</select></label><label>Language<input value={language} placeholder="Any language" maxLength={64} onChange={event=>setLanguage(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();void loadPage(inputFor({...filters,query:search.trim(),language:language.trim()}));}}}/></label><label className="collection-filter"><input type="checkbox" checked={filters.onlyCollection} onChange={event=>void loadPage(inputFor({...filters,onlyCollection:event.target.checked}))}/><Icon name="collection"/>Saved only</label><button className="icon-button" aria-label="Refresh Library" title="Refresh Library" disabled={busy} onClick={()=>void loadPage(inputFor(filters,page?.offset??0))}><Icon name="refresh"/></button></div>
      {filtered&&<div className="active-filters"><span>{[filters.query&&`Results for “${filters.query}”`,filters.platform&&platformNames[filters.platform],filters.language,filters.onlyCollection&&'Saved profiles'].filter(Boolean).join(' · ')}</span><button className="text-button" onClick={clear}>Clear filters<Icon name="close"/></button></div>}
      {busy&&<Loading label="Loading creators…"/>}
      {page&&<><div className="list-caption"><span>{page.items.length?page.offset+1:0}–{page.items.length?page.offset+page.items.length:0} of {page.total}</span><span>Analyzed</span></div><ul className="profile-list" aria-label="Creators">{page.items.map(creator=><li key={creator.id}><button className="profile-row" data-creator-id={creator.id} aria-label={`Open ${nameOf(creator)}`} onClick={()=>void open(creator.id)}><Artwork url={creator.avatar_url} name={nameOf(creator)} kind="creators"/><span className="profile-row-content"><span className="profile-row-title">{nameOf(creator)}{creator.favorite&&<Icon name="collection"/>}</span><span className="profile-row-summary">{creator.description||creator.handle||creator.source_identity.account_id||'No summary recorded'}</span><span className="row-tags"><span>{platformNames[creator.source_identity.platform]}</span>{(creator.source_identity.platform==='twitch'||creator.source_identity.platform==='instagram')&&<span>Manual · discovery unavailable</span>}<span>{creator.languages.length?creator.languages.join(', '):'Languages unknown'}</span></span></span><span className="row-subscribers">{creator.follower_count===null?'Followers unknown':`${new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(creator.follower_count)} followers`}</span><span className="row-date">{analyzedDate(creator.last_analyzed_at)}</span><Icon name="chevron"/></button></li>)}</ul></>}
      {error&&<ErrorNotice error={error} onRetry={failedInput?()=>void loadPage(failedInput):undefined}/>}
      {!busy&&!error&&page?.items.length===0&&<EmptyState title={filtered?'No matching profiles':'No creators yet'} action={filtered?<button className="button secondary" onClick={clear}>Clear filters</button>:undefined}/>}
      {page&&page.total>0&&<div className="creator-library-pagination"><button className="button secondary" disabled={busy||page.offset===0} onClick={()=>void loadPage(inputFor(filters,Math.max(0,page.offset-50)))}>Previous page</button><button className="button secondary" disabled={busy||page.offset+page.limit>=page.total} onClick={()=>void loadPage(inputFor(filters,page.offset+page.limit))}>Next page</button></div>}
    </div>
    {route.kind==='loading'&&<><button className="text-button back-button" onClick={back}><Icon name="arrow"/>Back to creators</button>{route.error?<ErrorNotice error={route.error} onRetry={()=>void open(route.id,true)}/>:<Loading label="Loading creator…"/>}</>}
    {route.kind==='detail'&&<>{route.saved&&<div className="creator-saved-message" role="status"><Icon name="check"/>Saved</div>}<CreatorRecord key={route.creator.id} api={api} creator={route.creator} initialSection={route.section} refreshToken={route.creator.revision} onBack={back} onEdit={edit}/></>}
    {route.kind==='editor'&&<CreatorEditor api={api} initial={route.initial} onSaved={saved} onCancel={cancel} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/>}
    {route.kind==='identity'&&<CreatorIdentityEditor api={api} initial={route.creator} onSaved={saved} onCancel={cancel} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/>}
  </div>;
}
