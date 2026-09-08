import {useEffect,useRef,type ReactNode} from 'react';
import {createPortal} from 'react-dom';

export function CreatorDialog({title,children,actions,onClose}:{title:string;children:ReactNode;actions:ReactNode;onClose:()=>void}) {
  const panel=useRef<HTMLDivElement>(null);
  useEffect(()=>{
    const previous=document.activeElement as HTMLElement|null;
    panel.current?.querySelector<HTMLElement>('button:not(:disabled),input:not(:disabled)')?.focus();
    return()=>{if(previous?.isConnected&&!previous.matches(':disabled'))previous.focus({preventScroll:true});};
  },[]);
  return createPortal(<div className="modal-backdrop"><div ref={panel} className="confirm-dialog" role="dialog" aria-modal="true" aria-label={title} onKeyDown={event=>{
    if(event.key==='Escape'){event.preventDefault();onClose();}
    if(event.key==='Tab'){
      const controls=panel.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]');
      if(!controls?.length)return;
      const first=controls[0],last=controls[controls.length-1];
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
      else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
    }
  }}><h2>{title}</h2>{children}<div className="game-dialog-actions">{actions}</div></div></div>,document.body);
}
