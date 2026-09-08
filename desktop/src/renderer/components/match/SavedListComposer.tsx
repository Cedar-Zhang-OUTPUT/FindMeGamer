import type {useSavedSetOperation} from './useSavedSetOperation';
import {ErrorNotice} from '../Primitives';
import './savedListComposer.css';

export interface SavedListDraft { queryId:string; name:string; ids:string[] }
export function SavedListComposer({draft,onChange,onCancel,onSave,onMarkLoaded,onClear,disabled,current}:{draft:SavedListDraft;onChange:(value:SavedListDraft)=>void;onCancel:()=>void;onSave:()=>void;onMarkLoaded:()=>void;onClear:()=>void;disabled:boolean;current:boolean}){
  const count=draft.ids.length,valid=Boolean(draft.name.trim())&&[...draft.name].length<=255&&count>0&&count<=600;
  return <form className="saved-list-composer" aria-label="Save candidate list" onSubmit={event=>{event.preventDefault();if(valid&&!disabled&&current)onSave();}}>
    <label>List name<input autoFocus value={draft.name} maxLength={510} disabled={disabled} onChange={event=>onChange({...draft,name:event.target.value})}/></label>
    <div className="saved-list-members"><span>{count} marked</span><button type="button" className="text-button" disabled={disabled||!current||count>=600} onClick={onMarkLoaded}>Mark loaded</button><button type="button" className="text-button" disabled={disabled||!count} onClick={onClear}>Clear marks</button></div>
    <div className="saved-list-actions"><button type="button" className="button secondary" disabled={disabled} onClick={onCancel}>Cancel list</button><button className="button primary" disabled={disabled||!current||!valid}>Save {count} {count===1?'creator':'creators'}</button></div>
  </form>;
}
export function SavedListNotice({operation,onRetry,onCheck,onRepair}:{operation:ReturnType<typeof useSavedSetOperation>;onRetry:()=>void;onCheck:()=>void;onRepair?:()=>void}){
  return <>{operation.busy&&<p role="status">Saving list…</p>}{operation.locked&&<section className="match-uncertain" aria-label="Unconfirmed list"><h3>Save not confirmed</h3><p>{operation.retryAllowed?'Retry keeps the same name and marked creators.':'Credentials changed. Check the list in its original workspace.'}</p><div className="button-row"><button className="button primary" disabled={!operation.retryAllowed} onClick={onRetry}>Retry same save</button><button className="button secondary" onClick={onCheck}>Check saved lists</button></div></section>}{operation.state.error&&<ErrorNotice error={operation.state.error}/>} {operation.state.error&&onRepair&&<button className="button secondary" onClick={onRepair}>Open Settings</button>}</>;
}
