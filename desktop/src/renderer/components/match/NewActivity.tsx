import {useEffect,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {GameDetail,NavigationGuard} from '../../../shared/games';
import type {ActivityView,ActivityPage} from '../../../shared/match';
import {LinkedGamePicker} from '../creators/LinkedGamePicker';
import {GameEditor} from '../GameEditor';
import {Artwork,ErrorNotice,Icon,Loading} from '../Primitives';
import {matchReadError} from './matchMutation';
import {useMatchOperation,type OperationReceipt} from './useMatchOperation';
import {MatchOperationNotice} from './MatchOperationNotice';
import {useMatchGuard} from './useMatchGuard';

export function NewActivity({api,onCreated,onCancel,onNavigationGuardChange,onConnectionRepair}:{api:DesktopBridge;onCreated:(activity:ActivityView)=>void;onCancel:()=>void;onNavigationGuardChange?:(guard:NavigationGuard|null)=>void;onConnectionRepair?:()=>void}){
  const [name,setName]=useState(''),[game,setGame]=useState<GameDetail|null>(null),[references,setReferences]=useState<string[]>([]);
  const [choice,setChoice]=useState<string|null>(null),[pickGame,setPickGame]=useState(true);
  const [editor,setEditor]=useState<{base:GameDetail|null}|null>(null);
  const [gameError,setGameError]=useState<PublicError|null>(null),[gameBusy,setGameBusy]=useState(false);
  const [errors,setErrors]=useState<Record<string,string>>({}),[lookup,setLookup]=useState<ActivityPage|null>(null),[lookupError,setLookupError]=useState<PublicError|null>(null),[lookupBusy,setLookupBusy]=useState(false);
  const alive=useRef(true);useEffect(()=>{alive.current=true;return()=>{alive.current=false;};},[]);
  const operation=useMatchOperation(api.match);
  const guard=useMatchGuard({operation,dirty:Boolean(name||game),enabled:!editor,onChange:onNavigationGuardChange,onDiscard:()=>{setName('');setGame(null);setChoice(null);setReferences([]);setPickGame(true);}});
  useEffect(()=>{
    let current=true;if(!choice){setGameBusy(false);setGameError(null);return;}
    setGameBusy(true);setGameError(null);
    void api.games.detail(choice).then(result=>{if(!current)return;if(result.ok){setGame(result.data);setReferences([]);setPickGame(false);}else setGameError(result.error);}).catch(()=>{if(current)setGameError(matchReadError);}).finally(()=>{if(current)setGameBusy(false);});
    return()=>{current=false;};
  },[api.games,choice]);
  function complete(receipt:OperationReceipt|null){if(receipt&&'game_id' in receipt.data){onNavigationGuardChange?.(null);onCreated(receipt.data);}}
  async function submit(){
    const next:Record<string,string>={};if(!name.trim())next.name='Enter an activity name.';if(!game||gameBusy||gameError)next.game='Choose a saved game.';setErrors(next);if(Object.keys(next).length)return;
    complete(await operation.execute({kind:'createActivity',data:{name:name.trim(),game_id:game!.id,reference_work_ids:[...references]}}));
  }
  async function check(offset=0){setLookupBusy(true);setLookupError(null);try{const response=await api.match.activities({limit:50,offset});if(alive.current){if(response.ok)setLookup(response.data);else setLookupError(response.error);}}catch{if(alive.current)setLookupError(matchReadError);}finally{if(alive.current)setLookupBusy(false);}}
  if(editor)return <GameEditor api={api} initial={editor.base} onSaved={saved=>{setGame(saved);setChoice(null);setGameError(null);setGameBusy(false);setErrors(previous=>{const {game:_,...remaining}=previous;return remaining;});setReferences(previous=>previous.filter(id=>saved.reference_works.some(work=>work.id===id)));setEditor(null);setPickGame(false);}} onCancel={()=>setEditor(null)} onNavigationGuardChange={onNavigationGuardChange} onConnectionRepair={onConnectionRepair}/>;
  const disabled=operation.busy||operation.locked;
  return <section className="match-new-activity"><button className="text-button back-button" onClick={()=>guard.request(onCancel)}><Icon name="arrow"/>Activities</button><div className="page-heading"><h1>New activity</h1></div>
    <div className="form-field"><label htmlFor="activity-name">Activity name</label><input id="activity-name" value={name} maxLength={255} disabled={disabled} aria-invalid={Boolean(errors.name)} onChange={event=>setName(event.target.value)} placeholder="e.g. Autumn launch"/>{errors.name&&<p className="game-field-error">{errors.name}</p>}</div>
    <section className="match-game-choice" aria-label="Activity game"><div className="section-heading"><h2>Game</h2><button className="button secondary" disabled={disabled} onClick={()=>setEditor({base:null})}>New game</button></div>
      {game&&!pickGame?<><div className="match-chosen-game"><Artwork url={game.cover_url} name={game.name||'Game'} kind="games"/><div><h3>{game.name||game.website_url||'Unnamed game'}</h3>{game.developer&&<span>{game.developer}</span>}</div><button className="text-button" disabled={disabled} onClick={()=>setPickGame(true)}>Change game</button><button className="text-button" disabled={disabled} onClick={()=>setEditor({base:game})}>Edit game</button></div>
        {game.reference_works.length>0&&<details className="match-references"><summary>Reference works</summary><div>{game.reference_works.filter(work=>work.id).map(work=><label key={work.id}><input type="checkbox" disabled={disabled} checked={references.includes(work.id!)} onChange={event=>setReferences(previous=>event.target.checked?[...previous,work.id!]:previous.filter(id=>id!==work.id))}/>{work.name||work.url||'Unnamed reference'}</label>)}</div></details>}
      </>:<LinkedGamePicker api={api} value={choice} disabled={disabled} onChange={id=>{setChoice(id);if(!id){setGame(null);setReferences([]);}}} error={errors.game}/>}
      {gameBusy&&<Loading label="Loading game…"/>}{gameError&&<ErrorNotice error={gameError} onRetry={()=>{setChoice(null);requestAnimationFrame(()=>setChoice(choice));}}/>}{errors.game&&!pickGame&&<p className="game-field-error">{errors.game}</p>}
    </section>
    <MatchOperationNotice operation={operation} onRetry={()=>void operation.retry().then(complete)} onCheck={()=>void check()} onRepair={onConnectionRepair}/>
    {lookupBusy&&<Loading label="Checking activities…"/>}{lookupError&&<ErrorNotice error={lookupError} onRetry={()=>void check(lookup?.offset??0)}/>}
    {lookup&&<section className="match-recovery-records" aria-label="Saved activities"><h3>Choose only the activity created by this request</h3>{lookup.items.map(item=><div key={item.id}><span><strong>{item.name}</strong><code>{item.id}</code></span><button className="button secondary" onClick={()=>{operation.confirmSaved();onNavigationGuardChange?.(null);onCreated(item);}}>Use saved activity</button></div>)}<div className="button-row"><button disabled={lookupBusy||lookup.offset===0} className="text-button" onClick={()=>void check(Math.max(0,lookup.offset-50))}>Previous activities</button><button disabled={lookupBusy||lookup.offset+lookup.limit>=lookup.total} className="text-button" onClick={()=>void check(lookup.offset+50)}>More activities</button></div></section>}
    <div className="match-primary-action"><button className="button primary" disabled={disabled||gameBusy} onClick={()=>void submit()}>Create activity<Icon name="chevron"/></button></div>{guard.dialog}
  </section>;
}
