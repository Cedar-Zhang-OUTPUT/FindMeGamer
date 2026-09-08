// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {act,cleanup,render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import {LanguageFilter} from '../src/renderer/components/creators/CreatorLibraryFilters';
import {GameLibrary} from '../src/renderer/components/GameLibrary';
import type {DesktopBridge,Result} from '../src/shared/bridge';
import type {GamePage} from '../src/shared/games';
import {gameFixture} from './game-fixtures';
afterEach(cleanup);
it('keeps language choices within 30 when presets are combined with custom labels',async()=>{
  const apply=vi.fn(),user=userEvent.setup();render(<LanguageFilter value={Array.from({length:30},(_,i)=>`Custom ${i+1}`)} onApply={apply}/>);
  await user.click(screen.getByRole('button',{name:/Languages:/}));
  expect(screen.getByRole('checkbox',{name:'English · en'})).toBeDisabled();
  await user.click(screen.getByRole('checkbox',{name:'Custom 1'}));
  await user.click(screen.getByRole('checkbox',{name:'English · en'}));await user.click(screen.getByRole('button',{name:'Apply'}));
  expect(apply.mock.calls[0][0]).toHaveLength(30);expect(apply.mock.calls[0][0]).toContain('en');
});
it('discards late Game filter replies and only renders actual updated timestamps',async()=>{
  const page=(name:string):Result<GamePage>=>({ok:true,data:{items:[gameFixture(name)],total:1,limit:24,offset:0}});
  let finish!:(value:Result<GamePage>)=>void;
  const list=vi.fn<DesktopBridge['games']['list']>().mockResolvedValueOnce(page('Initial')).mockImplementationOnce(()=>new Promise(resolve=>finish=resolve)).mockResolvedValueOnce(page('Newest'));
  render(<GameLibrary api={{games:{list}} as unknown as DesktopBridge} active/>);const user=userEvent.setup();
  await screen.findByRole('button',{name:'Open Initial'});
  expect(screen.queryByTitle('Updated')).not.toBeInTheDocument();
  await user.selectOptions(screen.getByRole('combobox',{name:'Website'}),'missing');await user.selectOptions(screen.getByRole('combobox',{name:'Website'}),'available');
  await screen.findByRole('button',{name:'Open Newest'});await act(async()=>finish(page('Old filter')));
  expect(screen.getByRole('button',{name:'Open Newest'})).toBeVisible();expect(screen.queryByRole('button',{name:'Open Old filter'})).not.toBeInTheDocument();
});
