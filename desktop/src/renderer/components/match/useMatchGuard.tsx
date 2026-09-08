import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {NavigationGuard} from '../../../shared/games';
import {CreatorDialog} from '../creators/CreatorDialog';
import type {useMatchOperation} from './useMatchOperation';

export function useMatchGuard({operation,dirty,enabled=true,readRepair=false,onChange,onDiscard}:{operation:ReturnType<typeof useMatchOperation>;dirty:boolean;enabled?:boolean;readRepair?:boolean;onChange?: (guard:NavigationGuard|null)=>void;onDiscard:()=>void}){
  const [pending,setPending]=useState<(()=>void)|null>(null);
  const discard=useRef(onDiscard);discard.current=onDiscard;
  const needed=dirty||operation.busy||operation.locked;
  const guard=useMemo<NavigationGuard>(()=>{
    const handler:NavigationGuard=proceed=>setPending(()=>proceed);
    if(readRepair||operation.state.error||operation.locked)handler.recovery={credentialsChanged:operation.credentialsChanged};
    return handler;
  },[readRepair,operation.state.error,operation.locked,operation.credentialsChanged]);
  useEffect(()=>{if(!enabled)return;onChange?.(needed?guard:null);return()=>onChange?.(null);},[enabled,needed,guard,onChange]);
  const request=useCallback((proceed:()=>void)=>{if(needed)guard(proceed);else proceed();},[needed,guard]);
  const dialog=pending&&<CreatorDialog title={operation.locked?'Unconfirmed request':'Unsaved Match changes'} onClose={()=>setPending(null)} actions={<><button className="button secondary" onClick={()=>setPending(null)}>Keep working</button><button className="text-button" disabled={operation.busy||operation.locked} onClick={()=>{const proceed=pending;setPending(null);discard.current();onChange?.(null);proceed();}}>Discard changes</button></>}><p>{operation.locked?'Resolve the saved task before leaving. It may still be running on the server.':operation.busy?'The request is still being submitted.':'Discard these unsaved changes?'}</p></CreatorDialog>;
  return {request,dialog};
}
