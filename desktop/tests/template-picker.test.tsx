// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {TemplatePicker} from '../src/renderer/components/match/TemplatePicker';
import type {TemplateCatalog} from '../src/shared/drafts';
afterEach(cleanup);
const builtin={name:'LIMINAL original',subject:'Original subject',fixed_fragments:['<p>Hi ',', ',' about ','. ','</p><p>Original signature</p>'],fixed_hash:'a'.repeat(64),source_metadata:{kind:'canonical' as const,document_id:'doc',revision:69,steam_app_id:'4952700',raw_hash:'b'.repeat(64)},key:'liminal-revision-69' as const,requires_explicit_registration:true as const};
const catalog:TemplateCatalog={items:[{...builtin,id:'version',game_id:'game',created_at:'2026-09-08T00:00:00Z'}],builtin};
function props(){return {game:{id:'game',name:'My game',steamAppId:null},catalog,selectedId:'version',active:true,busy:false,recipientCount:3,onSelect:vi.fn(),onRegister:vi.fn(async()=>true),onCreate:vi.fn(async()=>false),onContinue:vi.fn(),onRetry:vi.fn(),onDirtyChange:vi.fn()};}
it('reads a locked full preview without registering or generating and keeps creation explicit',async()=>{
  const p=props(),user=userEvent.setup();render(<TemplatePicker {...p}/>);
  expect(p.onRegister).not.toHaveBeenCalled();expect(p.onCreate).not.toHaveBeenCalled();expect(p.onContinue).not.toHaveBeenCalled();
  const frame=screen.getByTitle('Template preview');expect(frame).toHaveAttribute('sandbox','');expect(frame).toHaveAttribute('srcdoc',expect.stringContaining('Original signature'));
  await user.click(screen.getByRole('button',{name:'Create 3 drafts'}));expect(p.onContinue).toHaveBeenCalledOnce();
});
it('does not offer canonical registration for a different Steam identity',async()=>{
  const p=props(),user=userEvent.setup();render(<TemplatePicker {...p} game={{...p.game,steamAppId:'123'}}/>);
  await user.click(screen.getByRole('button',{name:'Preview original'}));
  expect(screen.getByRole('button',{name:'Use original for My game'})).toBeDisabled();expect(p.onRegister).not.toHaveBeenCalled();
});
it('preserves a failed new-version draft and hidden detour, converting only its explicit new body',async()=>{
  const p=props(),user=userEvent.setup(),view=render(<TemplatePicker {...p}/>);
  await user.click(screen.getByRole('button',{name:'New version'}));
  await user.type(screen.getByRole('textbox',{name:'Version name'}),'My version');await user.type(screen.getByRole('textbox',{name:'Subject'}),'My subject');
  const body='Hi {{firstName}},\n{{channelName}} & {{reference}}. {{observation}}';
  fireEvent.change(screen.getByRole('textbox',{name:'Fixed email text'}),{target:{value:body}});
  await user.click(screen.getByRole('button',{name:'Save new version'}));
  expect(p.onCreate).toHaveBeenCalledWith({name:'My version',subject:'My subject',fixed_fragments:['<p>Hi ',',<br>',' &amp; ','. ','</p>']});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Save new version'})).toBeEnabled());
  view.rerender(<TemplatePicker {...p} active={false}/>);view.rerender(<TemplatePicker {...p}/>);
  expect(screen.getByRole('textbox',{name:'Fixed email text'})).toHaveValue(body);expect(p.onDirtyChange).toHaveBeenLastCalledWith(true);
  await user.click(screen.getByRole('button',{name:'Cancel new version'}));expect(screen.queryByRole('textbox',{name:'Fixed email text'})).not.toBeInTheDocument();expect(p.onDirtyChange).toHaveBeenLastCalledWith(false);
});
