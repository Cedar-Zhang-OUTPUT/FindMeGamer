// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,fireEvent,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {TemplatePicker} from '../src/renderer/components/match/TemplatePicker';
import type {TemplateCatalog} from '../src/shared/drafts';
afterEach(cleanup);
const builtin={name:'Game template',subject:'Original subject',fixed_fragments:['<p>Hi ',', ',' about ','. ','</p><p>Original signature</p>'],fixed_hash:'a'.repeat(64),source_metadata:{kind:'game_bound' as const,document_id:null,revision:1,steam_app_id:null,raw_hash:null,game_id:'game',game_revision:3,game_fingerprint:'b'.repeat(64),sender_name:null},key:'game-outreach-v1' as const,requires_explicit_registration:true as const};
const catalog:TemplateCatalog={items:[{...builtin,id:'version',game_id:'game',created_at:'2026-09-08T00:00:00Z'}],builtin};
function props(){return {game:{id:'game',name:'My game',steamAppId:null},catalog,selectedId:'version',active:true,busy:false,recipientCount:3,onSelect:vi.fn(),onRegister:vi.fn(async()=>true),onCreate:vi.fn(async()=>false),onContinue:vi.fn(),onRetry:vi.fn(),onDirtyChange:vi.fn()};}
it('reads a locked full preview without registering or generating and keeps creation explicit',async()=>{
  const p=props(),user=userEvent.setup();render(<TemplatePicker {...p}/>);
  expect(p.onRegister).not.toHaveBeenCalled();expect(p.onCreate).not.toHaveBeenCalled();expect(p.onContinue).not.toHaveBeenCalled();
  const frame=screen.getByTitle('Template preview');expect(frame).toHaveAttribute('sandbox','');expect(frame).toHaveAttribute('srcdoc',expect.stringContaining('Original signature'));
  await user.click(screen.getByRole('button',{name:'Create 3 drafts'}));expect(p.onContinue).toHaveBeenCalledOnce();
});
it('offers no arbitrary template creation or fixed-text editing',()=>{
 const p=props();render(<TemplatePicker {...p}/>);
 expect(screen.queryByRole('button',{name:'New version'})).not.toBeInTheDocument();expect(screen.queryByRole('button',{name:'Create a template'})).not.toBeInTheDocument();expect(screen.queryByRole('textbox',{name:'Fixed email text'})).not.toBeInTheDocument();expect(p.onCreate).not.toHaveBeenCalled();
});
it('keeps the old canonical preview read-only and cannot generate new drafts from it',()=>{
 const p=props();render(<TemplatePicker {...p} catalog={{items:[],builtin:{...builtin,key:'liminal-revision-69',source_metadata:{...builtin.source_metadata,kind:'canonical'}}}}/>);
 expect(screen.getByRole('button',{name:'Use this template'})).toBeDisabled();expect(screen.queryByRole('button',{name:'Create 3 drafts'})).not.toBeInTheDocument();
});
it('uses the server-provided game-bound template without hardcoding a Steam identity',async()=>{
 const p=props(),user=userEvent.setup();render(<TemplatePicker {...p} catalog={{...catalog,items:[]}} selectedId={null} game={{...p.game,steamAppId:'123'}}/>);
 await user.click(screen.getByRole('button',{name:'Use this template'}));expect(p.onRegister).toHaveBeenCalledOnce();expect(p.onCreate).not.toHaveBeenCalled();
});
it('never reuses a historic arbitrary version as the current fixed template',()=>{
 const p=props(),historic={...catalog.items[0],source_metadata:{...catalog.items[0].source_metadata,kind:'user_saved' as const}};
 render(<TemplatePicker {...p} catalog={{...catalog,items:[historic]}}/>);
 expect(screen.queryByRole('button',{name:'Create 3 drafts'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'Use this template'})).toBeEnabled();expect(p.onSelect).toHaveBeenCalledWith(null);
});
