import {useEffect,useRef,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {TemplateCatalog,TemplateVersionCreate} from '../../../shared/drafts';
import {ErrorNotice,Loading} from '../Primitives';
import {EmailDocument} from './EmailDocument';
import {templatePreviewHTML} from './templateText';
import './templatePicker.css';

export type TemplateGame={id:string;name:string;steamAppId:string|null};
export type NewTemplateText=Pick<TemplateVersionCreate,'name'|'subject'|'fixed_fragments'>;
type Props={game:TemplateGame;catalog:TemplateCatalog|null;selectedId:string|null;active:boolean;busy:boolean;error?:PublicError|null;recipientCount:number;onSelect:(id:string|null)=>void;onRegister:()=>Promise<boolean>;onContinue:()=>void;onRetry:()=>void;onDirtyChange?:(dirty:boolean)=>void};
export function TemplatePicker({game,catalog,selectedId,active,busy,error,recipientCount,onSelect,onRegister,onContinue,onRetry,onDirtyChange}:Props){
  const [saving,setSaving]=useState(false),pending=useRef(false);
  const current=catalog?.items.find(item=>item.game_id===game.id&&item.source_metadata.kind==='game_bound'&&item.fixed_hash===catalog.builtin.fixed_hash);
  const selected=current?.id===selectedId?current:null;
  const preview=current??catalog?.builtin;
  const disabled=busy||saving||!active||catalog?.builtin.source_metadata.kind!=='game_bound';
  useEffect(()=>{onDirtyChange?.(false);},[onDirtyChange]);
  useEffect(()=>{if(active&&catalog&&selectedId!==(current?.id??null))onSelect(current?.id??null);},[active,catalog,current?.id,selectedId,onSelect]);
  async function register(){
    if(disabled||pending.current||!catalog)return;
    pending.current=true;setSaving(true);
    try{await onRegister();}finally{pending.current=false;setSaving(false);}
  }
  return <section className="template-picker" aria-label="Email template" hidden={!active}>
    <header className="template-toolbar"><div><h2>Template</h2><span className="muted">{game.name}</span></div><span className="status-badge">4 personalization slots</span></header>
    {catalog?.builtin.source_metadata.kind!=='game_bound'&&catalog&&<p role="status">Update the service to use the game-bound template.</p>}
    {error&&<ErrorNotice error={error} onRetry={onRetry}/>}
    {!catalog&&!error&&<Loading label="Loading template…"/>}
    {preview&&<><div className="template-mail-heading"><span>Subject</span><h3>{preview.subject}</h3><span className="status-badge">Fixed text · read only</span></div>
      <EmailDocument html={templatePreviewHTML(preview)} title="Template preview"/>
      <details className="template-provenance"><summary>Template details</summary><dl><div><dt>Source</dt><dd>Original structure · revision {preview.source_metadata.revision}</dd></div><div><dt>Fixed content hash</dt><dd>{preview.fixed_hash}</dd></div>{preview.source_metadata.document_id&&<div><dt>Document</dt><dd>{preview.source_metadata.document_id}</dd></div>}</dl></details>
    </>}
    <footer className="template-actions"><div className="template-primary">{current?<button className="button primary" disabled={disabled||!selected||recipientCount<1||recipientCount>600} onClick={onContinue}>Create {recipientCount} drafts</button>:<button className="button primary" disabled={disabled||!catalog} onClick={()=>void register()}>{saving?'Preparing template…':'Use this template'}</button>}<span>Uses model quota · no email sent</span></div></footer>
  </section>;
}
