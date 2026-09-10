import type {KeyboardEvent} from 'react';

/** Chromium chains wheel input, but not page keys from a focused horizontal scroller. */
export function tableScrollKeys(event:KeyboardEvent<HTMLElement>){
 const target=event.target;
 if(event.defaultPrevented||event.altKey||event.ctrlKey||event.metaKey||event.shiftKey||
  !(target instanceof HTMLElement)||!target.classList.contains('review-table-scroll'))return;
 const main=event.currentTarget;
 if(main.scrollHeight<=main.clientHeight)return;
 const page=Math.max(1,main.clientHeight-40);
 const delta={ArrowDown:40,ArrowUp:-40,PageDown:page,PageUp:-page,Home:-main.scrollHeight,End:main.scrollHeight}[event.key];
 if(delta===undefined)return;
 event.preventDefault();
 main.scrollBy({top:delta,behavior:'instant'});
}
