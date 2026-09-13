export function scopedSelection(selected:string[],scope:string[],checked:boolean,limit=Infinity){
 const visible=new Set(scope);
 const next=checked?[...new Set([...selected,...scope])]:selected.filter(id=>!visible.has(id));
 return next.length>limit?null:next;
}
export function SelectionActions({scope,count,selected,onSelect,onClear,disabled=false,limitExceeded=false,selectDisabled=false}:{scope:string;count:number;selected:number;onSelect:()=>void;onClear:()=>void;disabled?:boolean;limitExceeded?:boolean;selectDisabled?:boolean}){
 return <div className="button-row" role="group" aria-label={`${scope} selection`}>
  <span className="muted">{scope} · {selected}/{count}</span>
  <button type="button" className="text-button" disabled={disabled||!count||selected===count||limitExceeded||selectDisabled} onClick={onSelect}>Select all</button>
  <button type="button" className="text-button" disabled={disabled||!selected} onClick={onClear}>Deselect all</button>
  {limitExceeded&&<span className="muted">Selection limit exceeded</span>}
 </div>;
}
export function ScopedSelectionActions({scope,ids,selected,onChange,disabled=false,limit=Infinity}:{scope:string;ids:string[];selected:string[];onChange:(next:string[])=>void;disabled?:boolean;limit?:number}){
 const unique=[...new Set(ids)],all=scopedSelection(selected,unique,true,limit);
 return <SelectionActions scope={scope} count={unique.length} selected={unique.filter(id=>selected.includes(id)).length} disabled={disabled} limitExceeded={all===null}
  onSelect={()=>{if(all)onChange(all);}} onClear={()=>onChange(scopedSelection(selected,unique,false)!)} />;
}
