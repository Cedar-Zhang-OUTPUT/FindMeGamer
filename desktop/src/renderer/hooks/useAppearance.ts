import { useCallback, useEffect, useRef, useState } from 'react';
import type { PublicError } from '../../shared/bridge';
import type { Preferences, PreferencesAPI } from '../../shared/preferences';

const fallback: Preferences = {appearance:'system',fontSize:'default',automaticUpdates:true};
const sizes = {small:14,medium:15,default:16,large:18,'extra-large':20};
const unavailable: PublicError = {code:'preferences_unavailable',message:'Could not save local preferences. Try again.',retryable:true};

export function useAppearance(api: PreferencesAPI | undefined) {
  const [preferences,setPreferences] = useState(fallback);
  const [error,setError] = useState<PublicError|null>(null);
  const [busy,setBusy] = useState(false);
  const generation = useRef(0);
  const locked = useRef(false);
  const current = useRef(preferences);current.current=preferences;
  useEffect(()=>{
    let live=true;
    const revision=++generation.current;
    if(api) void api.read().then(result=>{if(live && revision===generation.current){if(result.ok)setPreferences(result.data);else setError(result.error);}}).catch(()=>{if(live)setError(unavailable);});
    return()=>{live=false;};
  },[api]);
  useEffect(()=>{
    const query=window.matchMedia?.('(prefers-color-scheme: dark)');
    const apply=()=>{document.documentElement.dataset.theme=preferences.appearance==='system'?(query?.matches?'dark':'light'):preferences.appearance;};
    apply(); query?.addEventListener('change',apply);
    document.documentElement.style.fontSize=`${sizes[preferences.fontSize]}px`;
    return()=>query?.removeEventListener('change',apply);
  },[preferences.appearance,preferences.fontSize]);
  const save=useCallback(async(input:Partial<Preferences>|'restore')=>{
    if(!api || locked.current)return;
    locked.current=true;generation.current++;setBusy(true);setError(null);
    const previous=current.current;
    setPreferences(input==='restore'?{...previous,appearance:'system',fontSize:'default'}:{...previous,...input});
    try {const result=await(input==='restore'?api.restoreAppearance():api.update(input));if(result.ok)setPreferences(result.data);else {setPreferences(previous);setError(result.error);}}
    catch {setPreferences(previous);setError(unavailable);}
    finally {locked.current=false;setBusy(false);}
  },[api]);
  return {preferences,error,busy,save};
}
export type AppearanceState = ReturnType<typeof useAppearance>;
