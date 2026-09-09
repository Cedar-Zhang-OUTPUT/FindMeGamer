// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import {SourceImport} from '../src/renderer/components/analyze/SourceImport';
import {gameFixture} from './game-fixtures';
import {creatorFormFixture} from './creator-form-fixtures';
afterEach(cleanup);
it('offers in-place manual entry after a definite Steam failure and retains the original link',async()=>{
 const steamImport=vi.fn(async()=>({ok:false,error:{code:'steam_unavailable',message:'Steam unavailable',retryable:true}}));
 render(<SourceImport api={{analysis:{steamImport}} as unknown as DesktopBridge} target={{kind:'game'}} onSaved={vi.fn()} onClose={vi.fn()}/>);
 const user=userEvent.setup(),url='https://store.steampowered.com/app/900000001';
 await user.type(screen.getByRole('textbox',{name:'Steam URL'}),url);expect(steamImport).not.toHaveBeenCalled();
 await user.keyboard('{Enter}');await user.click(await screen.findByRole('button',{name:'Enter manually'}));
 expect(screen.getByRole('textbox',{name:'Original Steam URL'})).toHaveValue(url);
 expect(screen.getByRole('textbox',{name:'Name'})).toBeVisible();
 expect(steamImport).toHaveBeenCalledOnce();
 await user.type(screen.getByRole('textbox',{name:'Name'}),'Manual draft');
 await user.click(screen.getByRole('button',{name:'Cancel'}));
 await user.click(await screen.findByRole('button',{name:'Continue editing'}));expect(screen.getByRole('textbox',{name:'Name'})).toHaveValue('Manual draft');
 await user.click(screen.getByRole('button',{name:'Cancel'}));await user.click(await screen.findByRole('button',{name:'Discard changes'}));
 expect(screen.getByRole('textbox',{name:'Steam URL'})).toHaveValue(url);expect(screen.getByRole('button',{name:'Retry source request'})).toBeVisible();
});
it('imports source only with selected revision and never queues analysis',async()=>{
 const game=gameFixture(),saved=vi.fn(),create=vi.fn(),steamImport=vi.fn(async()=>({ok:true,data:{...game,revision:1}}));
 const api={analysis:{steamImport,create}} as unknown as DesktopBridge;
 render(<SourceImport api={api} target={{kind:'game',game}} onSaved={saved} onClose={vi.fn()}/>);
 const user=userEvent.setup();await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/900000001');await user.click(screen.getByRole('button',{name:'Import source'}));
 await waitFor(()=>expect(saved).toHaveBeenCalled());expect(steamImport).toHaveBeenCalledWith(expect.objectContaining({gameId:game.id,expectedRevision:0,url:'https://store.steampowered.com/app/900000001'}));expect(create).not.toHaveBeenCalled();
});
it('freezes uncertain input and retries exactly the same key/body',async()=>{
 const steamImport=vi.fn(async()=>({ok:false,error:{code:'analysis_write_unknown',message:'Check the original request.',retryable:false}}));
 render(<SourceImport api={{analysis:{steamImport}} as unknown as DesktopBridge} target={{kind:'game'}} onSaved={vi.fn()} onClose={vi.fn()}/>);
 const user=userEvent.setup();await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/900000001');await user.click(screen.getByRole('button',{name:'Import source'}));await screen.findByRole('button',{name:'Check same request'});
 expect(screen.getByRole('textbox',{name:'Steam URL'})).toBeDisabled();expect(screen.queryByRole('button',{name:'Cancel'})).not.toBeInTheDocument();
 expect(screen.queryByRole('button',{name:'Enter manually'})).not.toBeInTheDocument();
 await user.click(screen.getByRole('button',{name:'Check same request'}));expect(steamImport).toHaveBeenCalledTimes(2);expect(steamImport.mock.calls[1]).toEqual(steamImport.mock.calls[0]);
});
it('YouTube binding uses the Creator UUID/revision, not legacy creation',async()=>{
 const creator=creatorFormFixture({source_identity:{platform:'youtube',account_id:null,canonical_url:null,revision:1},profile_url:'https://www.youtube.com/@harbor'}),bindYouTube=vi.fn(async()=>({ok:true,data:creator}));
 render(<SourceImport api={{analysis:{bindYouTube}} as unknown as DesktopBridge} target={{kind:'youtube',creator}} onSaved={vi.fn()} onClose={vi.fn()}/>);
 await userEvent.setup().click(screen.getByRole('button',{name:'Bind channel'}));await waitFor(()=>expect(bindYouTube).toHaveBeenCalledWith(expect.objectContaining({creatorId:creator.id,expectedRevision:creator.revision,url:creator.profile_url})));
});
it('a failed replay does not erase an earlier unknown write',async()=>{
 const steamImport=vi.fn().mockResolvedValueOnce({ok:false,error:{code:'analysis_write_unknown',message:'Unconfirmed.',retryable:false}}).mockResolvedValue({ok:false,error:{code:'workspace_key_invalid',message:'Reconnect.',retryable:false}});
 render(<SourceImport api={{analysis:{steamImport}} as unknown as DesktopBridge} target={{kind:'game'}} onSaved={vi.fn()} onClose={vi.fn()}/>);const user=userEvent.setup();await user.type(screen.getByRole('textbox',{name:'Steam URL'}),'https://store.steampowered.com/app/1');await user.click(screen.getByRole('button',{name:'Import source'}));await user.click(await screen.findByRole('button',{name:'Check same request'}));await screen.findByText('Reconnect.');expect(screen.getByRole('textbox',{name:'Steam URL'})).toBeDisabled();expect(screen.queryByRole('button',{name:'Cancel'})).not.toBeInTheDocument();
});
