import {useEffect,useRef,useState} from 'react';
import type {PublicError} from '../../../shared/bridge';
import type {TemplateCatalog,TemplateVersionCreate} from '../../../shared/drafts';
import {ErrorNotice,Loading} from '../Primitives';
import {EmailDocument} from './EmailDocument';
import {newTemplateFragments,SLOT_KEYS,SLOT_LABELS,templatePreviewHTML} from './templateText';
import './templatePicker.css';

export type TemplateGame={id:string;name:string;steamAppId:string|null};
export type NewTemplateText=Pick<TemplateVersionCreate,'name'|'subject'|'fixed_fragments'>;
type Props={game:TemplateGame;catalog:TemplateCatalog|null;selectedId:string|null;active:boolean;busy:boolean;error?:PublicError|null;recipientCount:number;onSelect:(id:string|null)=>void;onRegister:()=>Promise<boolean>;onCreate:(data:NewTemplateText)=>Promise<boolean>;onContinue:()=>void;onRetry:()=>void;onDirtyChange?:(dirty:boolean)=>void};
const initialBody='Hi {{firstName}},\n\n{{channelName}}\n{{reference}}\n{{observation}}';
export function TemplatePicker({game,catalog,selectedId,active,busy,error,recipientCount,onSelect,onRegister,onCreate,onContinue,onRetry,onDirtyChange}:Props){
  const [mode,setMode]=useState<'catalog'|'original'|'new'>('catalog');
  const [name,setName]=useState(''),[subject,setSubject]=useState(''),[body,setBody]=useState(initialBody),[validation,setValidation]=useState(''),[saving,setSaving]=useState(false);
  const pending=useRef(false),bodyField=useRef<HTMLTextAreaElement>(null);
  const dirty=mode==='new';
  useEffect(()=>{onDirtyChange?.(dirty);},[dirty,onDirtyChange]);
  const selected=catalog?.items.find(item=>item.id===selectedId&&item.game_id===game.id);
  const preview=mode==='original'?catalog?.builtin:selected;
  const disabled=busy||saving||!active;
  function cancel(){setMode('catalog');setName('');setSubject('');setBody(initialBody);setValidation('');}
  async function save(){
    if(disabled||pending.current)return;
    let fixed_fragments:string[];
    try{
      if(!name.trim())throw new Error('Enter a version name.');
      if(!subject.trim()||subject.length>998||/[\r\n\x00-\x1f\x7f]/.test(subject))throw new Error('Enter a single-line subject, up to 998 characters.');
      fixed_fragments=newTemplateFragments(body);
    }catch(cause){setValidation(cause instanceof Error?cause.message:'Check the template.');return;}
    pending.current=true;setSaving(true);setValidation('');
    try{if(await onCreate({name:name.trim(),subject:subject.trim(),fixed_fragments}))cancel();}
    finally{pending.current=false;setSaving(false);}
  }
  async function register(){if(disabled||pending.current)return;pending.current=true;setSaving(true);try{if(await onRegister())setMode('catalog');}finally{pending.current=false;setSaving(false);}}
  function insert(key:typeof SLOT_KEYS[number]){
    const field=bodyField.current,start=field?.selectionStart??body.length,end=field?.selectionEnd??start;
    const marker=`{{${key}}}`;setBody(value=>value.slice(0,start)+marker+value.slice(end));
    requestAnimationFrame(()=>{field?.focus();field?.setSelectionRange(start+marker.length,start+marker.length);});
  }
  return <section className="template-picker" aria-label="Email template" hidden={!active}>
    <header className="template-toolbar"><div><h2>{mode==='new'?'New template version':'Template'}</h2><span className="muted">{game.name}</span></div>{mode!=='new'&&<div className="button-row"><button className="text-button" disabled={disabled} onClick={()=>setMode(mode==='original'?'catalog':'original')}>{mode==='original'?'Back to versions':'Preview original'}</button><button className="button secondary" disabled={disabled} onClick={()=>setMode('new')}>New version</button></div>}</header>
    {error&&<ErrorNotice error={error} onRetry={onRetry}/>}
    {mode==='new'?<form className="template-new" onSubmit={event=>{event.preventDefault();void save();}}>
      <label>Version name<input value={name} maxLength={200} disabled={disabled} onChange={event=>setName(event.target.value)}/></label>
      <label>Subject<input value={subject} maxLength={998} disabled={disabled} onChange={event=>setSubject(event.target.value)}/></label>
      <label>Fixed email text<textarea ref={bodyField} value={body} disabled={disabled} rows={14} onChange={event=>setBody(event.target.value)}/></label>
      <div className="template-slots" aria-label="Insert personalization slot">{SLOT_KEYS.map((key,index)=><button type="button" key={key} data-slot={key} disabled={disabled} onClick={()=>insert(key)}>{index+1}. {SLOT_LABELS[key]}</button>)}</div>
      {validation&&<p className="inline-warning" role="alert">{validation}</p>}
      <footer className="template-actions"><button type="button" className="text-button" disabled={disabled} onClick={cancel}>Cancel new version</button><button type="submit" className="button primary" disabled={disabled}>{saving?'Saving…':'Save new version'}</button></footer>
    </form>:<>
      {mode==='catalog'&&catalog&&<label className="template-version-field">Version<select aria-label="Template version" value={selected?.id??''} disabled={disabled} onChange={event=>onSelect(event.target.value||null)}><option value="">Choose a version</option>{catalog.items.filter(item=>item.game_id===game.id).map(item=><option key={item.id} value={item.id}>{item.name} · {new Date(item.created_at).toLocaleDateString('en-GB')}</option>)}</select></label>}
      {!catalog&&!error&&<Loading label="Loading templates…"/>}
      {preview?<><div className="template-mail-heading"><span>Subject</span><h3>{preview.subject}</h3><span className="status-badge">Fixed text · read only</span></div><EmailDocument html={templatePreviewHTML(preview)} title="Template preview"/>
        <details className="template-provenance"><summary>Version details</summary><dl><div><dt>Source</dt><dd>{preview.source_metadata.kind==='canonical'?`Original · revision ${preview.source_metadata.revision}`:'Saved version'}</dd></div><div><dt>Fixed content hash</dt><dd>{preview.fixed_hash}</dd></div>{preview.source_metadata.document_id&&<div><dt>Document</dt><dd>{preview.source_metadata.document_id}</dd></div>}</dl></details>
      </>:catalog&&<div className="template-empty"><h3>{catalog.items.length?'Choose a template':'No templates yet'}</h3>{!catalog.items.length&&<button className="button secondary" disabled={disabled} onClick={()=>setMode('new')}>Create a template</button>}</div>}
      <footer className="template-actions">{mode==='original'?<div className="template-primary"><button className="button primary" disabled={disabled||!catalog||Boolean(game.steamAppId&&game.steamAppId!=='4952700')} onClick={()=>void register()}>Use original for {game.name}</button>{game.steamAppId&&game.steamAppId!=='4952700'&&<span>LIMINAL original · different Steam game</span>}</div>:<div className="template-primary"><button className="button primary" disabled={disabled||!selected||recipientCount<1||recipientCount>600} onClick={onContinue}>Create {recipientCount} drafts</button><span>Uses model quota · no email sent</span></div>}</footer>
    </>}
  </section>;
}
