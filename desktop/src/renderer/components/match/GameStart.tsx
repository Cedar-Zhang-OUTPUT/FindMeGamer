import {useEffect,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {GamePage} from '../../../shared/games';
import {Artwork,ErrorNotice,Icon,Loading} from '../Primitives';

/** P1 task entry, deliberately not the optional relationship picker used in forms. */
export function GameStart({api,disabled,onUse,onSteam,onManage,refreshToken=0}:{api:DesktopBridge;disabled:boolean;onUse:(id:string)=>void;onSteam:()=>void;onManage:()=>void;refreshToken?:number}){
 const [query,setQuery]=useState(''),[request,setRequest]=useState({query:'',offset:0,attempt:0});
 const [page,setPage]=useState<GamePage|null>(null),[error,setError]=useState<PublicError|null>(null),[loading,setLoading]=useState(true);
 useEffect(()=>{let alive=true;setLoading(true);setError(null);
  void api.games.list({query:request.query,limit:24,offset:request.offset}).then(result=>{if(!alive)return;if(result.ok)setPage(result.data);else setError(result.error);}).catch(()=>{if(alive)setError({code:'network_error',message:'Could not load games.',retryable:true});}).finally(()=>{if(alive)setLoading(false);});return()=>{alive=false;};
 },[api.games,request,refreshToken]);
 const search=()=>setRequest(previous=>({query:query.trim(),offset:0,attempt:previous.attempt+1}));
 return <div className="game-start">
  <form className="game-start-search" onSubmit={event=>{event.preventDefault();search();}}>
   <div className="game-start-search-field"><Icon name="search"/><input type="search" aria-label="Search games" placeholder="Search by game name or ID" value={query} disabled={disabled} maxLength={255} onChange={event=>setQuery(event.target.value)}/><button type="submit" className="text-button" disabled={disabled||loading}>Search</button></div>
   <button type="button" className="button secondary" disabled={disabled} onClick={onManage}>Manage Library</button>
  </form>
  {error&&<ErrorNotice error={error} onRetry={()=>setRequest(previous=>({...previous,attempt:previous.attempt+1}))}/>}
  <div className="game-start-results" aria-busy={loading}>
   {loading&&<Loading label="Loading games…"/>}
   {!loading&&!error&&page?.items.length===0&&<div className="game-start-empty"><h2>{request.query?'No matching games':'Your game Library is empty'}</h2><button className="button secondary" disabled={disabled} onClick={onSteam}>Import from Steam</button></div>}
   {!error&&page?.items.map(game=><article className="game-start-card" aria-label={game.name||game.website_url||'Unnamed game'} key={game.id}>
    <Artwork kind="games" name={game.name||'Game'} url={game.cover_url}/><div className="game-start-card-copy"><h2>{game.name||game.website_url||'Unnamed game'}</h2><span>{[game.developer,game.steam_app_id?`Steam · ${game.steam_app_id}`:null].filter(Boolean).join(' · ')||'Saved game'}</span></div>
    <button className="button secondary game-start-use" aria-label={`Use game ${game.name||'Unnamed game'}`} disabled={disabled||loading} onClick={()=>onUse(game.id)}>Use game<Icon name="chevron"/></button>
   </article>)}
  </div>
  {page&&page.total>page.limit&&<nav className="game-start-pagination" aria-label="Game pages"><button className="button secondary" disabled={disabled||loading||page.offset===0} onClick={()=>setRequest(previous=>({...previous,offset:Math.max(0,page.offset-page.limit)}))}>Previous games</button><span>{page.offset+1}–{page.offset+page.items.length} of {page.total}</span><button className="button secondary" disabled={disabled||loading||page.offset+page.limit>=page.total} onClick={()=>setRequest(previous=>({...previous,offset:page.offset+page.limit}))}>Next games</button></nav>}
  <section className="game-start-steam"><img className="game-start-steam-art" src="/assets/steam-entry.svg" alt=""/><div><h2>Start with a Steam link</h2><p>Import the store page, then review your game.</p><button className="button secondary" disabled={disabled} onClick={onSteam}>Use Steam link</button></div></section>
 </div>;
}
