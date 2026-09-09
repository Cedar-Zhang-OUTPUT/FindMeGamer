import {useCallback,useEffect,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {GameDetail,NavigationGuard} from '../../../shared/games';
import type {ActivityView,ActivityPage} from '../../../shared/match';
import {GameStart} from './GameStart';
import {GameLibrary} from '../GameLibrary';
import {GameEditor} from '../GameEditor';
import {Artwork,ErrorNotice,Icon,Loading} from '../Primitives';
import {matchReadError} from './matchMutation';
import {useMatchOperation,type OperationReceipt} from './useMatchOperation';
import {MatchOperationNotice} from './MatchOperationNotice';
import {useMatchGuard} from './useMatchGuard';
import {SourceImport} from '../analyze/SourceImport';

export function NewActivity({api,initialGame,onCreated,onCancel,onNavigationGuardChange,onConnectionRepair}:{api:DesktopBridge;initialGame?:GameDetail;onCreated:(activity:ActivityView)=>void;onCancel:()=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void}){
  const [brief,setBrief]=useState('');
  const [name,setName]=useState(''),[game,setGame]=useState<GameDetail|null>(initialGame??null),[references,setReferences]=useState<string[]>([]);
  const [choice,setChoice]=useState<string|null>(null),[pickGame,setPickGame]=useState(!initialGame);
  const [editor,setEditor]=useState<{base:GameDetail|null}|null>(initialGame?{base:initialGame}:null);
  const [branch,setBranch]=useState<'library'|'steam'>('library'),[steamVisited,setSteamVisited]=useState(false),[steamLocked,setSteamLocked]=useState(false);
  const [managing,setManaging]=useState(false),[libraryRefresh,setLibraryRefresh]=useState(0);
  const libraryGuard=useRef<NavigationGuard|null>(null);
  const guards=useRef<{own:NavigationGuard|null;editor:NavigationGuard|null;steam:NavigationGuard|null}>({own:null,editor:null,steam:null});
  const publish=useRef(onNavigationGuardChange);publish.current=onNavigationGuardChange;
  const register=useCallback((owner:'own'|'editor'|'steam',value:NavigationGuard|null)=>{
    guards.current[owner]=value;
    const entries=Object.values(guards.current).filter((item):item is NavigationGuard=>Boolean(item));
    if(!entries.length){publish.current?.(null);return;}
    const combined:NavigationGuard=proceed=>{
      const finish=()=>{const own=guards.current.own;own?own(proceed):proceed();};
      const source=()=>{const steam=guards.current.steam;if(steam){setBranch('steam');setPickGame(true);steam(finish);}else finish();};
      const edit=guards.current.editor;edit?edit(source):source();
    };
    if(entries.some(item=>item.recovery))combined.recovery={credentialsChanged:()=>entries.forEach(item=>item.recovery?.credentialsChanged())};
    publish.current?.(combined);
  },[]);
  const ownGuard=useCallback((value:NavigationGuard|null)=>register('own',value),[register]);
  const editorGuard=useCallback((value:NavigationGuard|null)=>register('editor',value),[register]);
  const steamGuard=useCallback((value:NavigationGuard|null)=>register('steam',value),[register]);
  const [gameError,setGameError]=useState<PublicError|null>(null),[gameBusy,setGameBusy]=useState(false);
  const [errors,setErrors]=useState<Record<string,string>>({}),[lookup,setLookup]=useState<ActivityPage|null>(null),[lookupError,setLookupError]=useState<PublicError|null>(null),[lookupBusy,setLookupBusy]=useState(false);
  const alive=useRef(true);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const operation=useMatchOperation(api.match);
  const guard=useMatchGuard({operation,dirty:Boolean(name||game),onChange:ownGuard,onDiscard:()=>{setBrief('');setName('');setGame(null);setChoice(null);setReferences([]);setPickGame(true);}});
  useEffect(()=>{
    let current=true;if(!choice){setGameBusy(false);setGameError(null);return;}
    setGameBusy(true);setGameError(null);
    void api.games.detail(choice).then(result=>{if(!current)return;if(result.ok){setGame(result.data);setReferences([]);setPickGame(false);setEditor({base:result.data});}else setGameError(result.error);}).catch(()=>{if(current)setGameError(matchReadError);}).finally(()=>{if(current)setGameBusy(false);});
    return()=>{current=false;};
  },[api.games,choice]);
  function complete(receipt:OperationReceipt|null){if(receipt&&'game_id' in receipt.data){onNavigationGuardChange?.(null);onCreated(receipt.data);}}
  async function submit(saved=game,selectedReferences=references){
    const next:Record<string,string>={};if(!saved||gameBusy)next.game='Choose a saved game.';setErrors(next);if(Object.keys(next).length||!saved)return;
    const activityName=(name.trim()||saved.name||saved.website_url||'Game outreach').slice(0,255);
    complete(await operation.execute({kind:'createActivity',data:{name:activityName,game_id:saved.id,...(brief.trim()?{campaign_brief:brief.trim()}:{}),reference_work_ids:selectedReferences.filter(id=>saved.reference_works.some(work=>work.id===id))}}));
  }
  async function check(offset=0){setLookupBusy(true);setLookupError(null);try{const response=await api.match.activities({limit:50,offset});if(alive.current){if(response.ok)setLookup(response.data);else setLookupError(response.error);}}catch{if(alive.current)setLookupError(matchReadError);}finally{if(alive.current)setLookupBusy(false);}}
  function acceptGame(saved:GameDetail,selectedReferences=references,intent:'continue'|'leave'='continue'){setGame(saved);setChoice(null);setGameError(null);setGameBusy(false);setReferences(selectedReferences);setErrors({});setEditor(null);setPickGame(intent==='leave');setLibraryRefresh(value=>value+1);if(intent==='continue')void submit(saved,selectedReferences);}
  function switchBranch(next:'library'|'steam'){if(steamLocked||disabled||gameBusy)return;if(next==='steam')setSteamVisited(true);setBranch(next);}
  const disabled=operation.busy||operation.locked;
  return <><section hidden={Boolean(editor)||managing} className="match-new-activity"><button className="text-button back-button" onClick={()=>{const source=guards.current.steam;if(source){setBranch('steam');setPickGame(true);source(()=>guard.request(onCancel));}else guard.request(onCancel);}}><Icon name="arrow"/>Activities</button><div className="page-heading"><h1>{pickGame?'Choose a game':'Continue to matching'}</h1></div>
    <section className="match-game-entry" aria-label="Activity game">
      {game&&!pickGame&&<div className="match-chosen-game"><Artwork url={game.cover_url} name={game.name||'Game'} kind="games"/><div><h2>{game.name||game.website_url||'Unnamed game'}</h2><span>{name||game.name}</span></div><button className="text-button" disabled={disabled} onClick={()=>setEditor({base:game})}>Edit game</button></div>}
      <div hidden={!pickGame}><div className="segmented" role="tablist" aria-label="Game source">{(['library','steam'] as const).map(target=><button key={target} role="tab" id={`match-source-${target}`} aria-controls={`match-source-panel-${target}`} aria-selected={branch===target} tabIndex={branch===target?0:-1} disabled={disabled||steamLocked||gameBusy} onClick={()=>switchBranch(target)} onKeyDown={event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();const next=event.key==='Home'?'library':event.key==='End'?'steam':branch==='library'?'steam':'library';switchBranch(next);document.getElementById(`match-source-${next}`)?.focus();}}}>{target==='library'?'Library':'Steam'}</button>)}</div>
      <div role="tabpanel" id="match-source-panel-library" aria-labelledby="match-source-library" hidden={branch!=='library'}><GameStart api={api} refreshToken={libraryRefresh} disabled={disabled||steamLocked||gameBusy} onUse={id=>{setChoice(null);requestAnimationFrame(()=>setChoice(id));}} onSteam={()=>switchBranch('steam')} onManage={()=>setManaging(true)}/></div>
      <div role="tabpanel" id="match-source-panel-steam" aria-labelledby="match-source-steam" hidden={branch!=='steam'}>{steamVisited&&<SourceImport api={api} onManual={()=>{setEditor({base:null});setPickGame(false);}} target={{kind:'game'}} onLockChange={setSteamLocked} onSaved={record=>{const imported=record as GameDetail;setSteamVisited(false);steamGuard(null);setChoice(null);setGame(imported);setGameError(null);setReferences([]);setEditor({base:imported});setPickGame(false);}} onClose={()=>{setSteamVisited(false);steamGuard(null);setBranch('library');}} onNavigationGuardChange={steamGuard} onConnectionRepair={onConnectionRepair}/>}</div></div>
      {gameBusy&&<Loading label="Loading game…"/>}{gameError&&<ErrorNotice error={gameError} onRetry={()=>{setChoice(null);requestAnimationFrame(()=>setChoice(choice));}}/>}{errors.game&&!pickGame&&<p className="game-field-error">{errors.game}</p>}
    </section>
    <MatchOperationNotice operation={operation} onRetry={()=>void operation.retry().then(complete)} onCheck={()=>void check()} onRepair={onConnectionRepair}/>
    {lookupBusy&&<Loading label="Checking activities…"/>}{lookupError&&<ErrorNotice error={lookupError} onRetry={()=>void check(lookup?.offset??0)}/>}
    {lookup&&<section className="match-recovery-records" aria-label="Saved activities"><h3>Choose only the activity created by this request</h3>{lookup.items.map(item=><div key={item.id}><span><strong>{item.name}</strong><code>{item.id}</code></span><button className="button secondary" onClick={()=>{operation.confirmSaved();onNavigationGuardChange?.(null);onCreated(item);}}>Use saved activity</button></div>)}<div className="button-row"><button disabled={lookupBusy||lookup.offset===0} className="text-button" onClick={()=>void check(Math.max(0,lookup.offset-50))}>Previous activities</button><button disabled={lookupBusy||lookup.offset+lookup.limit>=lookup.total} className="text-button" onClick={()=>void check(lookup.offset+50)}>More activities</button></div></section>}
    {!pickGame&&operation.state.phase==='idle'&&operation.state.error&&<div className="match-primary-action"><button className="button primary" disabled={disabled} onClick={()=>void submit()}>Continue to matching<Icon name="chevron"/></button></div>}{guard.dialog}
  </section>{editor&&<GameEditor key={editor.base?.id??'new'} api={api} initial={editor.base} continuationLabel="Continue to matching" referenceSelection={{ids:references,onChange:setReferences}} headerAccessory={<><details className="match-activity-name"><summary>Activity name · Optional</summary><label htmlFor="activity-name">Activity name</label><input id="activity-name" value={name} maxLength={255} onChange={event=>setName(event.target.value)} placeholder={editor.base?.name||'Uses the game name'}/></details><details className="match-activity-name"><summary>Campaign brief · Optional</summary><label htmlFor="new-campaign-brief">Campaign brief</label><textarea id="new-campaign-brief" value={brief} maxLength={5000} rows={3} onChange={event=>setBrief(event.target.value)} placeholder="Promotion focus and creator preferences"/></details></>} onSaved={acceptGame} onCancel={()=>{setEditor(null);setPickGame(true);setChoice(null);}} onNavigationGuardChange={editorGuard} onConnectionRepair={onConnectionRepair}/>}
  {managing&&<section className="match-library-detour"><button className="text-button back-button" onClick={()=>{const close=()=>{setManaging(false);setLibraryRefresh(value=>value+1);};libraryGuard.current?libraryGuard.current(close):close();}}><Icon name="arrow"/>Back to game selection</button><h1>Game Library</h1><GameLibrary api={api} active onUseForMatch={selected=>{setManaging(false);setLibraryRefresh(value=>value+1);setGame(selected);setReferences([]);setEditor({base:selected});setPickGame(false);}} onNavigationGuardChange={value=>{libraryGuard.current=value;editorGuard(value);}} onConnectionRepair={onConnectionRepair}/></section>}
  </>;
}
