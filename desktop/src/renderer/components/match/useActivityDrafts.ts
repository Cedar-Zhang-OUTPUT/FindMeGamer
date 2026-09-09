import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {DesktopBridge,PublicError} from '../../../shared/bridge';
import type {CompositionView,DraftsAPI,SenderFacts,SlotValues,TemplateCatalog} from '../../../shared/drafts';
import type {RecipientBatchDetail} from '../../../shared/outreach';
import {useDraftOperation} from './useDraftOperation';
import type {DraftCommand,DraftReceipt} from './draftMutation';
import type {NewTemplateText,TemplateGame} from './TemplatePicker';

type Props={api:Pick<DesktopBridge,'drafts'|'outreach'>&{games:Pick<DesktopBridge['games'],'detail'>};activityId:string;gameId:string|null;active:boolean;pollMs?:number};
type Mode={kind:'people'}|{kind:'template'}|{kind:'composition';id:string};
type DirtyPart='template'|'editor'|'facts';
const scopeError:PublicError={code:'invalid_response',message:'The returned draft set does not match these prepared people. Check the original request.',retryable:false};
const readError:PublicError={code:'draft_read_failed',message:'Could not load drafts. Try again.',retryable:true};
const asError=(error:unknown):PublicError=>error&&typeof error==='object'&&'code'in error&&'message'in error?error as PublicError:readError;
/** Creation and readback keep every frozen recipient in its original order. */
export function compositionMatchesBatch(value:CompositionView,batch:RecipientBatchDetail):boolean{
  return value.activity_id===batch.activity_id&&value.recipient_batch_id===batch.id&&value.recipient_count===batch.recipient_count
    &&value.drafts.length===batch.recipients.length&&value.drafts.every((row,index)=>row.composition_id===value.id&&row.input_order===index
      &&row.recipient_snapshot_id===batch.recipients[index].id&&row.selection_id===batch.recipients[index].selection_id);
}
export function useActivityDrafts({api,activityId,gameId,active,pollMs=4000}:Props){
  const [mode,setMode]=useState<Mode>({kind:'people'}),[batch,setBatch]=useState<RecipientBatchDetail|null>(null);
  const [catalog,setCatalog]=useState<TemplateCatalog|null>(null),[game,setGame]=useState<TemplateGame|null>(null),[selectedTemplate,setSelectedTemplate]=useState<string|null>(null);
  const [composition,setComposition]=useState<CompositionView|null>(null),[selectedId,setSelectedId]=useState<string|null>(null),[current,setCurrent]=useState(false);
  const [loading,setLoading]=useState(false),[error,setError]=useState<PublicError|null>(null),[notice,setNotice]=useState(''),[historyEpoch,setHistoryEpoch]=useState(0);
  const [dirtyParts,setDirtyParts]=useState<Record<DirtyPart,boolean>>({template:false,editor:false,facts:false}),[editorEpoch,setEditorEpoch]=useState(0);
  const [readback,setReadback]=useState<CompositionView|null>(null);
  const alive=useRef(true),generation=useRef(0),readSequence=useRef(0),pendingRead=useRef<number|null>(null),visible=useRef(active),wasActive=useRef(active);
  const batchRef=useRef(batch),compositionRef=useRef(composition),modeRef=useRef(mode),selectedRef=useRef(selectedId),templateRef=useRef(selectedTemplate);
  batchRef.current=batch;compositionRef.current=composition;modeRef.current=mode;selectedRef.current=selectedId;templateRef.current=selectedTemplate;visible.current=active;
  const guardedAPI=useMemo<DraftsAPI>(()=>({...api.drafts,createComposition:async input=>{
    const expected=batchRef.current?structuredClone(batchRef.current):null;
    const result=await api.drafts.createComposition(input);
    if(result.ok&&(!expected||!compositionMatchesBatch(result.data,expected)||result.data.template_version_id!==input.data.template_version_id))return {ok:false,error:scopeError};
    return result;
  }}),[api.drafts]);
  const operation=useDraftOperation(guardedAPI),busy=loading||operation.busy,locked=operation.locked;
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;generation.current++;readSequence.current++;};},[]);
  const dirty=Object.values(dirtyParts).some(Boolean);
  const setDirty=useCallback((part:DirtyPart,value:boolean)=>setDirtyParts(previous=>previous[part]===value?previous:{...previous,[part]:value}),[]);
  function discardEdits(){setDirtyParts({template:false,editor:false,facts:false});setEditorEpoch(value=>value+1);}
  function adopt(value:CompositionView){
    compositionRef.current=value;setComposition(value);setCurrent(true);
    setSelectedId(previous=>value.drafts.some(row=>row.id===previous)?previous:value.drafts[0]?.id??null);
  }
  const loadTemplates=useCallback(async()=>{
    if(!gameId)return false;const token=++readSequence.current,epoch=generation.current;setLoading(true);setError(null);
    try{
      const [gameResult,templatesResult]=await Promise.all([api.games.detail(gameId),api.drafts.templates({gameId})]);
      if(!alive.current||epoch!==generation.current||token!==readSequence.current)return false;
      if(!gameResult.ok)throw gameResult.error;if(!templatesResult.ok)throw templatesResult.error;
      if(gameResult.data.id!==gameId||templatesResult.data.items.some(item=>item.game_id!==gameId))throw scopeError;
      setGame({id:gameId,name:gameResult.data.name??'Untitled game',steamAppId:gameResult.data.source_identity.steam_app_id});setCatalog(templatesResult.data);return true;
    }catch(cause){if(alive.current&&epoch===generation.current&&token===readSequence.current)setError(asError(cause));return false;}
    finally{if(alive.current&&token===readSequence.current)setLoading(false);}
  },[api.games,api.drafts,gameId]);
  const readComposition=useCallback(async(id:string,foreground=false):Promise<CompositionView|null>=>{
    if(pendingRead.current!==null)return null;
    const epoch=generation.current,token=++readSequence.current;pendingRead.current=token;if(foreground)setLoading(true);setError(null);
    try{
      const result=await api.drafts.composition(id);if(!result.ok)throw result.error;
      if(!alive.current||epoch!==generation.current||token!==readSequence.current)return null;
      if(result.data.id!==id||result.data.activity_id!==activityId)throw scopeError;
      let original=batchRef.current;
      if(!original||original.id!==result.data.recipient_batch_id){const response=await api.outreach.batch({activityId,id:result.data.recipient_batch_id});if(!response.ok)throw response.error;original=response.data;}
      if(!alive.current||epoch!==generation.current||token!==readSequence.current)return null;
      if(!compositionMatchesBatch(result.data,original))throw scopeError;
      batchRef.current=original;setBatch(original);return result.data;
    }catch(cause){if(alive.current&&epoch===generation.current&&token===readSequence.current){setError(asError(cause));setCurrent(false);}return null;}
    finally{if(pendingRead.current===token)pendingRead.current=null;if(alive.current&&token===readSequence.current)setLoading(false);}
  },[api.drafts,api.outreach,activityId]);
  const refresh=useCallback(async()=>{const state=modeRef.current;if(state.kind==='template'){await loadTemplates();return;}if(state.kind!=='composition')return;const value=await readComposition(state.id,true);if(value)adopt(value);},[loadTemplates,readComposition]);
  useEffect(()=>{
    const returning=active&&!wasActive.current;wasActive.current=active;
    if(returning&&mode.kind!=='people')void refresh();
    if(!active){readSequence.current++;pendingRead.current=null;setLoading(false);setCurrent(false);}
  },[active,mode.kind,refresh]);
  const polling=active&&mode.kind==='composition'&&composition?.drafts.some(row=>row.status==='pending'||row.status==='running')&&!operation.busy&&!operation.locked;
  useEffect(()=>{
    if(!polling||mode.kind!=='composition')return;
    const timer=setInterval(()=>{if(pendingRead.current!==null)return;void readComposition(mode.id).then(value=>{if(value&&visible.current&&modeRef.current.kind==='composition'&&modeRef.current.id===value.id)adopt(value);});},pollMs);
    return()=>clearInterval(timer);
  },[polling,mode,readComposition,pollMs]);
  const credentialsChanged=useCallback(()=>{generation.current++;readSequence.current++;operation.credentialsChanged();setCurrent(false);setLoading(false);pendingRead.current=null;setReadback(null);setCatalog(null);setGame(null);setSelectedTemplate(null);setHistoryEpoch(value=>value+1);},[operation.credentialsChanged]);
  async function begin(original:RecipientBatchDetail){
    if(busy||locked||!active||original.activity_id!==activityId||original.recipient_count<1||original.recipient_count>600)return;
    batchRef.current=structuredClone(original);setBatch(batchRef.current);setMode({kind:'template'});setNotice('');setSelectedTemplate(null);setCatalog(null);await loadTemplates();
  }
  async function open(id:string){
    if(busy||locked||!active)return;
    // An explicit open owns the next read; show its local loading/error state.
    readSequence.current++;pendingRead.current=null;setMode({kind:'composition',id});setCurrent(false);setNotice('');setReadback(null);
    if(compositionRef.current?.id!==id){compositionRef.current=null;setComposition(null);setSelectedId(null);}
    const value=await readComposition(id,true);if(!value)return;
    adopt(value);
  }
  async function accept(receipt:DraftReceipt|null):Promise<boolean>{
    if(!receipt)return false;
    setReadback(null);
    if(receipt.kind==='createTemplate'||receipt.kind==='registerCanonical'){
      setCatalog(previous=>previous?{...previous,items:[receipt.data,...previous.items.filter(item=>item.id!==receipt.data.id)]}:previous);
      setSelectedTemplate(receipt.data.id);setNotice('Template saved');
    }else if(receipt.kind==='createComposition'||receipt.kind==='senderFacts'){
      adopt(receipt.data);setMode({kind:'composition',id:receipt.data.id});setHistoryEpoch(value=>value+1);setNotice(receipt.kind==='createComposition'?'Drafts created':'Confirmations saved');
    }else{
      const previous=compositionRef.current;
      if(!previous||receipt.data.composition_id!==previous.id||!previous.drafts.some(row=>row.id===receipt.data.id))return false;
      adopt({...previous,drafts:previous.drafts.map(row=>row.id===receipt.data.id?receipt.data:row)});
      setNotice(receipt.kind==='edit'?'Changes saved':receipt.kind==='refresh'?'Sources refreshed':'Generation queued');
    }
    return true;
  }
  async function execute(command:DraftCommand){readSequence.current++;pendingRead.current=null;setLoading(false);return accept(await operation.execute(command));}
  async function register(){if(busy||locked||!game||!catalog||catalog.builtin.source_metadata.kind!=='game_bound')return false;return execute({kind:'registerCanonical',gameId:game.id,canonicalFixedHash:catalog.builtin.fixed_hash});}
  async function createTemplate(data:NewTemplateText){if(busy||locked||!game)return false;return execute({kind:'createTemplate',data:{...data,game_id:game.id}});}
  async function create(){
    const original=batchRef.current,template=catalog?.items.find(item=>item.id===selectedTemplate&&item.game_id===gameId);
    if(busy||locked||!active||!original||!template||template.source_metadata.kind!=='game_bound'||template.fixed_hash!==catalog?.builtin.fixed_hash||dirty)return false;
    return execute({kind:'createComposition',activityId,data:{recipient_batch_id:original.id,template_version_id:template.id}});
  }
  function target(){return compositionRef.current?.drafts.find(row=>row.id===selectedRef.current);}
  async function saveDraft(values:SlotValues){const row=target();if(busy||locked||!current||!row)return false;return execute({kind:'edit',id:row.id,data:{expected_revision:row.revision,context_token:row.context_token,values},observedDraft:row});}
  async function regenerate(kind:'refresh'|'retry'){const row=target();if(busy||locked||!current||!row)return false;return execute({kind,id:row.id,data:{expected_revision:row.revision,context_token:row.context_token},observedDraft:row});}
  async function saveFacts(data:SenderFacts){const value=compositionRef.current;if(busy||locked||!current||!value)return false;return execute({kind:'senderFacts',compositionId:value.id,data,observedComposition:value});}
  async function check(){
    if(operation.state.phase!=='uncertain'||operation.busy||loading)return;
    const command=operation.state.attempt.command;
    if(operation.state.attempt.connectionChanged)return;
    if(command.kind==='registerCanonical'||command.kind==='createTemplate'){
      const epoch=generation.current,token=++readSequence.current;setLoading(true);
      try{const result=await api.drafts.templates({gameId:command.kind==='registerCanonical'?command.gameId:command.data.game_id});
        if(!alive.current||epoch!==generation.current||token!==readSequence.current)return;
        if(!result.ok){setError(result.error);return;}setCatalog(result.data);await accept(operation.confirmReadback({kind:'templates',items:result.data.items}));
      }catch(cause){if(alive.current&&epoch===generation.current&&token===readSequence.current)setError(asError(cause));}
      finally{if(alive.current&&token===readSequence.current)setLoading(false);}return;
    }
    const id=command.kind==='senderFacts'?command.compositionId:'observedDraft'in command?command.observedDraft?.composition_id:null;
    if(!id)return;const value=await readComposition(id,true);if(!value)return;
    const receipt=operation.confirmReadback({kind:'composition',data:value});
    if(receipt)await accept(receipt);else{setReadback(value);adopt(value);}
  }
  function reviewCurrent(){if(readback&&operation.reviewReadback(readback)){adopt(readback);setReadback(null);discardEdits();setNotice('Current version loaded · previous save remains unconfirmed');}}
  return {mode,setMode,batch,catalog,game,selectedTemplate,selectTemplate:setSelectedTemplate,composition,selectedId,setSelectedId,current,loading,busy,locked,error,notice,historyEpoch,dirty,editorEpoch,setDirty,discardEdits,operation,readback,
    begin,open,refresh,register,createTemplate,create,saveDraft,regenerate,saveFacts,check,reviewCurrent,credentialsChanged,retry:()=>operation.retry().then(accept)};
}
