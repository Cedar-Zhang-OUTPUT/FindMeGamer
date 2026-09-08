import {useEffect,useRef,useState,type ReactNode} from 'react';
import type {CandidateFilters,FollowerRange,PlanCreate} from '../../../shared/match';
import {Icon} from '../Primitives';
import {BUDGETS,COUNTRIES,FOLLOWER_PRESETS,LANGUAGES,cleanText,filtersFrom,rangeError,sameRange,validateConditions,type Choice} from './discoveryConditionState';
import './discoveryConditions.css';

type AudienceMode='any'|'presets'|'custom';
type FilterKind='languages'|'countries'|'followers';
export interface DiscoveryConditionsProps{value:PlanCreate;onChange:(value:PlanCreate)=>void;disabled?:boolean;onSubmit:()=>void;onCancel?:()=>void}
const optionId=(kind:string,code:string)=>`discovery-${kind}-${encodeURIComponent(code)}`;
const formatChoices=(values:string[],choices:readonly Choice[])=>values.length?values.map(code=>choices.find(item=>item[0]===code)?.[1]??code).join(', '):'Any';
function focusOption(kind:string,code:string){const id=optionId(kind,code),element=document.getElementById(id);if(element)element.focus();else requestAnimationFrame(()=>document.getElementById(id)?.focus());}

function FilterDialog({title,children,onCancel,onApply,invalid,disabled}:{title:string;children:ReactNode;onCancel:()=>void;onApply:()=>void;invalid?:boolean;disabled:boolean}){
  const panel=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    panel.current?.querySelector<HTMLElement>('input:not(:disabled),button:not(:disabled)')?.focus();
    return()=>{if(previous?.isConnected)previous.focus({preventScroll:true});};
  },[]);
  return <div className="discovery-dialog-backdrop"><div ref={panel} className="discovery-dialog" role="dialog" aria-modal="true" aria-labelledby="discovery-dialog-title" onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();onCancel();}
    if(event.key==='Enter'&&event.target instanceof HTMLInputElement)event.preventDefault();
    if(event.key==='Tab'){
      const controls=Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]')??[]);
      const first=controls[0],last=controls.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  }}><h3 id="discovery-dialog-title">{title}</h3><fieldset disabled={disabled} className="discovery-dialog-body">{children}</fieldset><div className="discovery-dialog-actions"><button type="button" className="button secondary" onClick={onCancel}>Cancel</button><button type="button" className="button primary" disabled={disabled||invalid} onClick={onApply}>Apply</button></div></div></div>;
}

function ChoiceDialog({kind,filters,onApply,onCancel,disabled}:{kind:'languages'|'countries';filters:Required<CandidateFilters>;onApply:(value:CandidateFilters)=>void;onCancel:()=>void;disabled:boolean}){
  const country=kind==='countries';
  const dictionary:readonly Choice[]=country?COUNTRIES:LANGUAGES;
  const [selected,setSelected]=useState(()=>[...filters[kind]]);
  const [pending,setPending]=useState(()=>[...filters.pending_country_labels]);
  const [unknown,setUnknown]=useState(()=>!filters[kind].length||filters[country?'include_unknown_country':'include_unknown_language']);
  const [search,setSearch]=useState(''),[custom,setCustom]=useState(''),[error,setError]=useState('');
  const options:readonly Choice[]=[...dictionary,...selected.filter(code=>!dictionary.some(item=>item[0]===code)).map(code=>[code,code] as const)];
  const visible=options.filter(item=>item.some(text=>text.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())));
  function toggle(code:string){
    const next=selected.includes(code)?selected.filter(item=>item!==code):[...selected,code];
    if(next.length>30){setError('Choose up to 30.');return;}
    setSelected(next);setError('');if(!next.length)setUnknown(true);else if(!selected.length)setUnknown(false);
  }
  function add(){
    const input=custom.trim();if(!input)return;
    if(!cleanText(input,country?100:64)){setError(`Use 1–${country?100:64} characters without control characters.`);return;}
    const match=dictionary.find(item=>item.some(text=>text.toLocaleLowerCase()===input.toLocaleLowerCase()));
    if(country&&!match){
      const duplicate=pending.find(item=>item.toLocaleLowerCase()===input.toLocaleLowerCase());
      if(duplicate){setCustom('');focusOption('pending',duplicate);return;}
      if(pending.length>=30){setError('Use up to 30 pending regions.');return;}
      setPending([...pending,input]);setCustom('');setError('');return;
    }
    const code=match?.[0]??selected.find(item=>item.toLocaleLowerCase()===input.toLocaleLowerCase())??input;
    const duplicate=selected.includes(code);
    if(!duplicate){
      if(selected.length>=30){setError('Choose up to 30.');return;}
      setSelected([...selected,code]);if(!selected.length)setUnknown(false);
    }
    setCustom('');setSearch('');setError('');if(duplicate)focusOption(kind,code);
  }
  return <FilterDialog title={country?'Country or region':'Content languages'} disabled={disabled} onCancel={onCancel} invalid={Boolean(custom.trim())} onApply={()=>onApply(country?{countries:selected,pending_country_labels:pending,include_unknown_country:unknown}:{languages:selected,include_unknown_language:unknown})}>
    <label className="discovery-search">Search {country?'countries':'languages'}<input type="search" value={search} onChange={event=>setSearch(event.target.value)}/></label>
    <div className="discovery-choice-tools"><label><input type="checkbox" checked={!selected.length} onChange={()=>{setSelected([]);setUnknown(true);if(country)setPending([]);}}/>Any</label>{country&&<button type="button" className="text-button" onClick={()=>{const next=[...new Set([...selected,'US','CA'])];if(next.length>30){setError('Choose up to 30.');return;}setSelected(next);if(!selected.length)setUnknown(false);setSearch('');setError('');}}>North America</button>}</div>
    <div className="discovery-choice-list">{visible.map(([code,label])=><label key={code}><input id={optionId(kind,code)} type="checkbox" checked={selected.includes(code)} onChange={()=>toggle(code)}/>{label===code?label:`${label} · ${code}`}</label>)}{!visible.length&&<p className="muted">No matches</p>}</div>
    <label className="discovery-unknown"><input type="checkbox" checked={unknown} disabled={!selected.length} onChange={event=>setUnknown(event.target.checked)}/>Include unknown {country?'countries':'languages'}</label>
    {country&&pending.length>0&&<div className="discovery-chips" aria-label="Pending regions">{pending.map(label=><span key={label}>{label} · Pending<button id={optionId('pending',label)} type="button" aria-label={`Remove pending region ${label}`} onClick={()=>setPending(pending.filter(item=>item!==label))}><Icon name="close"/></button></span>)}</div>}
    <div className="discovery-custom"><label>Other {country?'country or region':'language'}<input value={custom} maxLength={country?100:64} placeholder={country?'Name or code':'Language or code'} onChange={event=>{setCustom(event.target.value);setError('');}} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();add();}}}/></label><button type="button" className="button secondary" disabled={!custom.trim()} onClick={add}>Add</button></div>
    {country&&<p className="discovery-note">Unrecognized regions stay pending and do not filter results.</p>}
    {error&&<p role="alert" className="discovery-error">{error}</p>}
  </FilterDialog>;
}

function inferAudience(ranges:FollowerRange[]):AudienceMode{return !ranges.length?'any':ranges.every(range=>FOLLOWER_PRESETS.some(preset=>sameRange(range,preset.range)))?'presets':'custom';}
function AudienceDialog({filters,initialMode,onApply,onCancel,disabled}:{filters:Required<CandidateFilters>;initialMode:AudienceMode;onApply:(value:CandidateFilters,mode:AudienceMode)=>void;onCancel:()=>void;disabled:boolean}){
  const [mode,setMode]=useState(initialMode);
  const [presets,setPresets]=useState(()=>FOLLOWER_PRESETS.flatMap((preset,index)=>filters.follower_ranges.some(range=>sameRange(range,preset.range))?[index]:[]));
  const [minimum,setMinimum]=useState(initialMode==='custom'?String(filters.follower_ranges[0]?.minimum??''):'');
  const [maximum,setMaximum]=useState(initialMode==='custom'?String(filters.follower_ranges[0]?.maximum??''):'');
  const [unknown,setUnknown]=useState(initialMode==='any'||filters.include_unknown_followers);
  const ranges=mode==='any'?[]:mode==='presets'?presets.map(index=>FOLLOWER_PRESETS[index].range):[{minimum:minimum===''?null:Number(minimum),maximum:maximum===''?null:Number(maximum)}];
  const error=mode==='presets'&&!presets.length?'Choose at least one range.':rangeError(ranges);
  function choose(next:AudienceMode){if(next==='any')setUnknown(true);else if(mode==='any')setUnknown(false);setMode(next);}
  return <FilterDialog title="Followers" onCancel={onCancel} onApply={()=>onApply({follower_ranges:ranges,include_unknown_followers:unknown},mode)} invalid={Boolean(error)} disabled={disabled}>
    <div className="discovery-audience-modes">{(['any','presets','custom'] as const).map(item=><label key={item}><input type="radio" name="discovery-audience-mode" checked={mode===item} onChange={()=>choose(item)}/>{item==='any'?'Any':item==='presets'?'Presets':'Custom range'}</label>)}</div>
    <div className="discovery-preset-list">{FOLLOWER_PRESETS.map((preset,index)=><label key={preset.label}><input type="checkbox" checked={mode==='presets'&&presets.includes(index)} onChange={()=>{const current=mode==='presets'?presets:[];const next=current.includes(index)?current.filter(item=>item!==index):[...current,index].sort((a,b)=>a-b);setPresets(next);choose(next.length?'presets':'any');}}/>{preset.label}</label>)}</div>
    {mode==='custom'&&<div className="discovery-custom-range"><label>Minimum followers<input type="number" min="0" step="1" value={minimum} aria-invalid={Boolean(error)} onChange={event=>setMinimum(event.target.value)}/></label><label>Maximum followers<input type="number" min="0" step="1" value={maximum} aria-invalid={Boolean(error)} onChange={event=>setMaximum(event.target.value)}/></label></div>}
    <label className="discovery-unknown"><input type="checkbox" checked={unknown} disabled={mode==='any'} onChange={event=>setUnknown(event.target.checked)}/>Include unknown follower counts</label>
    {error&&<p role="alert" className="discovery-error">{error}</p>}
  </FilterDialog>;
}

export function DiscoveryConditions({value,onChange,disabled=false,onSubmit,onCancel}:DiscoveryConditionsProps){
  const filters=filtersFrom(value),keywords=value.keywords??[];
  const [dialog,setDialog]=useState<FilterKind|null>(null),[keyword,setKeyword]=useState(''),[keywordError,setKeywordError]=useState('');
  const [errors,setErrors]=useState<Record<string,string>>({});
  const form=useRef<HTMLFormElement>(null);
  const audience=useRef<{signature:string;mode:AudienceMode}|null>(null);
  function update(next:PlanCreate){onChange(next);setErrors({});}
  function applyFilters(next:CandidateFilters){update({...value,filters:{...filters,...next}});setDialog(null);}
  function addKeyword(){
    const input=keyword.trim();if(!input)return;
    if(!cleanText(input,100)){setKeywordError('Use 1–100 characters without control characters.');return;}
    const duplicate=keywords.find(word=>word.toLocaleLowerCase()===input.toLocaleLowerCase());
    if(duplicate){setKeyword('');focusOption('keyword',duplicate);return;}
    if(keywords.length>=20){setKeywordError('Use up to 20 keywords.');return;}
    update({...value,keywords:[...keywords,input]});setKeyword('');setKeywordError('');
  }
  const followerSummary=filters.follower_ranges.length?filters.follower_ranges.map(range=>range.maximum==null?`${(range.minimum??0).toLocaleString('en')}+`:`${(range.minimum??0).toLocaleString('en')}–${range.maximum.toLocaleString('en')}`).join(', '):'Any';
  const audienceSignature=JSON.stringify(filters.follower_ranges);
  return <form ref={form} className="discovery-conditions" noValidate onSubmit={event=>{
    event.preventDefault();if(disabled||dialog)return;
    if(keyword.trim()){setKeywordError('Add or clear this keyword before finding creators.');form.current?.querySelector<HTMLInputElement>('#discovery-keywords')?.focus();return;}
    const issues=validateConditions(value);setErrors(issues);
    if(Object.keys(issues).length){requestAnimationFrame(()=>{const first=form.current?.querySelector<HTMLElement>('[aria-invalid="true"]');for(let parent=first?.parentElement;parent;parent=parent.parentElement)if(parent instanceof HTMLDetailsElement)parent.open=true;first?.focus();});return;}
    onSubmit();
  }}>
    <fieldset className="discovery-fields" disabled={disabled}>
      <div className="discovery-condition-row"><span className="discovery-label" id="discovery-platforms-label">Platforms</span><div><div className="discovery-platforms" role="group" aria-labelledby="discovery-platforms-label">{(['youtube','x','twitch','instagram'] as const).map(platform=><label key={platform}><input type="checkbox" aria-invalid={Boolean(errors.platforms)} checked={value.platforms.some(item=>item===platform)} disabled={platform==='twitch'||platform==='instagram'} onChange={()=>{if(platform==='twitch'||platform==='instagram')return;update({...value,platforms:value.platforms.includes(platform)?value.platforms.filter(item=>item!==platform):[...value.platforms,platform]});}}/>{platform==='youtube'?'YouTube':platform==='x'?'X':platform==='twitch'?'Twitch · Unavailable':'Instagram · Unavailable'}</label>)}</div>{errors.platforms&&<p className="discovery-error" role="alert">{errors.platforms}</p>}</div></div>
      <div className="discovery-condition-row"><span className="discovery-label">Content languages</span><button type="button" className="discovery-filter-button" aria-label={`Content languages: ${formatChoices(filters.languages,LANGUAGES)}`} aria-haspopup="dialog" aria-invalid={Boolean(errors.languages)} onClick={()=>setDialog('languages')}>{formatChoices(filters.languages,LANGUAGES)}<Icon name="chevron"/></button></div>
      <div className="discovery-condition-row"><span className="discovery-label">Country or region</span><div><button type="button" className="discovery-filter-button" aria-label={`Country or region: ${formatChoices(filters.countries,COUNTRIES)}`} aria-haspopup="dialog" aria-invalid={Boolean(errors.countries||errors.pending_country_labels)} onClick={()=>setDialog('countries')}>{formatChoices(filters.countries,COUNTRIES)}<Icon name="chevron"/></button>{filters.pending_country_labels.length>0&&<span className="discovery-note">{filters.pending_country_labels.length} pending region{filters.pending_country_labels.length===1?'':'s'}</span>}</div></div>
      <div className="discovery-condition-row"><span className="discovery-label">Followers</span><button type="button" className="discovery-filter-button" aria-label={`Followers: ${followerSummary}`} aria-haspopup="dialog" aria-invalid={Boolean(errors.follower_ranges)} onClick={()=>setDialog('followers')}>{followerSummary}<Icon name="chevron"/></button></div>
      <div className="discovery-condition-row"><label className="discovery-label" htmlFor="discovery-keywords">Content keywords</label><div><div className="discovery-keyword-input"><input id="discovery-keywords" value={keyword} placeholder="Add a keyword" maxLength={100} aria-invalid={Boolean(errors.keywords||keywordError)} aria-describedby={errors.keywords||keywordError?'discovery-keyword-error':undefined} onChange={event=>{setKeyword(event.target.value);setKeywordError('');}} onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();addKeyword();}}}/><button type="button" className="button secondary" disabled={!keyword.trim()} onClick={addKeyword}>Add keyword</button></div><div className="discovery-chips">{keywords.map(word=><span key={word}>{word}<button id={optionId('keyword',word)} type="button" aria-label={`Remove keyword ${word}`} onClick={()=>update({...value,keywords:keywords.filter(item=>item!==word)})}><Icon name="close"/></button></span>)}</div>{(errors.keywords||keywordError)&&<p id="discovery-keyword-error" className="discovery-error" role="alert">{keywordError||errors.keywords}</p>}</div></div>
      <div className="discovery-condition-row"><label className="discovery-label" htmlFor="discovery-contact">Business email</label><div><select id="discovery-contact" value={filters.contact} onChange={event=>update({...value,filters:{...filters,contact:event.target.value as CandidateFilters['contact']}})}><option value="any">Any</option><option value="available">Public business email available</option><option value="missing">Business email missing</option></select><p className="discovery-note">Email availability is not consent to email.</p></div></div>
      <details className="discovery-advanced"><summary>Advanced limits</summary><div>{BUDGETS.map(({key,label,value:fallback,maximum})=><label key={key}>{label}<input type="number" min="1" max={maximum} step="1" aria-label={label} value={Number.isNaN(value[key])?'':value[key]??fallback} aria-invalid={Boolean(errors[key])} aria-describedby={errors[key]?`discovery-error-${key}`:undefined} onChange={event=>update({...value,[key]:event.target.value===''?NaN:Number(event.target.value)})}/>{errors[key]&&<span className="discovery-error" id={`discovery-error-${key}`}>{errors[key]}</span>}</label>)}</div></details>
    </fieldset>
    <div className="discovery-submit"><p>Uses model and platform quotas.</p><div>{onCancel&&<button type="button" className="button secondary" disabled={disabled} onClick={onCancel}>Cancel</button>}<button type="submit" className="button primary" disabled={disabled}>Find creators</button></div></div>
    {dialog==='languages'||dialog==='countries'?<ChoiceDialog kind={dialog} filters={filters} disabled={disabled} onCancel={()=>setDialog(null)} onApply={applyFilters}/>:dialog==='followers'?<AudienceDialog filters={filters} initialMode={audience.current?.signature===audienceSignature?audience.current.mode:inferAudience(filters.follower_ranges)} disabled={disabled} onCancel={()=>setDialog(null)} onApply={(next,mode)=>{audience.current={signature:JSON.stringify(next.follower_ranges),mode};applyFilters(next);}}/>:null}
  </form>;
}
