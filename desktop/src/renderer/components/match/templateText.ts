import type {SlotValues,TemplateContent} from '../../../shared/drafts';
export const SLOT_KEYS=['firstName','channelName','reference','observation'] as const;
export const SLOT_LABELS:Record<keyof SlotValues,string>={firstName:'Public name',channelName:'Channel name',reference:'Referenced work',observation:'Observation'};
export const escapeMailText=(value:string)=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]!));
/** For a NEW plain-text version only. Existing/canonical HTML is never round-tripped. */
export function newTemplateFragments(body:string):string[]{
  const markers=SLOT_KEYS.map(key=>`{{${key}}}`),found=body.match(/\{\{[^{}]*\}\}/g)??[];
  const rest=body.replace(/\{\{[^{}]*\}\}/g,'');
  if(found.join('|')!==markers.join('|')||rest.includes('{{')||rest.includes('}}'))throw new Error('Use each personalization slot once, in the shown order.');
  if(/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(body))throw new Error('Remove unsupported control characters.');
  const pieces:string[]=[];let offset=0;
  for(const marker of markers){const index=body.indexOf(marker,offset);pieces.push(body.slice(offset,index));offset=index+marker.length;}
  pieces.push(body.slice(offset));
  const fragments=pieces.map(piece=>escapeMailText(piece).replace(/\r\n?|\n/g,'<br>'));
  fragments[0]='<p>'+fragments[0];fragments[4]+='</p>';
  if(fragments.join('<slot/>').length>100_000)throw new Error('Shorten the fixed email text.');
  return fragments;
}
export function templatePreviewHTML(template:Pick<TemplateContent,'fixed_fragments'>,values?:SlotValues):string{
  return template.fixed_fragments.reduce((html,fragment,index)=>index===0?fragment:html+`<mark data-slot="${SLOT_KEYS[index-1]}">${escapeMailText(values?.[SLOT_KEYS[index-1]]??SLOT_LABELS[SLOT_KEYS[index-1]])}</mark>`+fragment,'');
}
