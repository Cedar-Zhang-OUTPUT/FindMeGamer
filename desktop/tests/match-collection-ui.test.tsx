// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest';
import {cleanup,render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {afterEach,expect,it,vi} from 'vitest';
import type {DesktopBridge} from '../src/shared/bridge';
import type {CollectionSettings} from '../src/shared/settings';
import {MatchActivity} from '../src/renderer/components/match/MatchActivity';
import {activityFixture,matchAPIMock,queryFixture} from './match-api-mock';
import {settingsBridgeMock} from './settings-fixtures';
afterEach(cleanup);
const settings=(enabled=false):CollectionSettings=>({items:[
  {platform:'youtube',enabled,implemented:true,credentials_configured:true,availability:enabled?'configured_unverified':'disabled'},
  {platform:'x',enabled:true,implemented:true,credentials_configured:true,availability:'configured_unverified'},
  {platform:'twitch',enabled:false,implemented:false,credentials_configured:false,availability:'disabled'},
  {platform:'instagram',enabled:false,implemented:false,credentials_configured:false,availability:'disabled'},
]});
function start(query=queryFixture()){
  const match=matchAPIMock();vi.mocked(match.query).mockResolvedValue({ok:true,data:query});
  const collection=vi.fn(async()=>({ok:true as const,data:settings()}));const api={...settingsBridgeMock(),match,settings:{collection}} as unknown as DesktopBridge;const onCollectionSettings=vi.fn();
  render(<MatchActivity api={api} activityId={activityFixture().id} active onBack={()=>{}} onOpenCreator={()=>{}} onCollectionSettings={onCollectionSettings}/>);
  return {api,collection,onCollectionSettings,user:userEvent.setup()};
}
it('keeps results and evaluation while an administrative pause disables only discovery continuation',async()=>{
  const query=queryFixture();query.sources.youtube={status:'more',blocked_reason:'collection_disabled'};
  const {api,user,onCollectionSettings}=start(query);
  expect(await screen.findByText('No available sources')).toBeVisible();
  expect(screen.getByRole('heading',{name:'Creator 1'})).toBeVisible();
  expect(screen.getByRole('button',{name:'Continue discovery'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Evaluate 2 loaded'})).toBeEnabled();
  expect(screen.getByText('YouTube · More available')).toBeVisible();
  await user.click(screen.getByRole('button',{name:'Collection settings'}));expect(onCollectionSettings).toHaveBeenCalledOnce();
  expect(api.match.continueDiscovery).not.toHaveBeenCalled();expect(api.match.stop).not.toHaveBeenCalled();
});
it('re-enabling and refreshing does not dispatch; only the explicit Continue button creates a batch',async()=>{
  const query=queryFixture();query.sources.youtube={status:'more',blocked_reason:'collection_disabled'};
  const {api,user,collection}=start(query);await screen.findByText('No available sources');
  collection.mockResolvedValue({ok:true,data:settings(true)});await user.click(screen.getByRole('button',{name:'Refresh activity'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Continue discovery'})).toBeEnabled());
  expect(screen.getByText('Ready to continue')).toBeVisible();expect(api.match.continueDiscovery).not.toHaveBeenCalled();
  await user.click(screen.getByRole('button',{name:'Continue discovery'}));expect(api.match.continueDiscovery).toHaveBeenCalledOnce();
});
it('a disabled YouTube channel does not suppress the enabled X source',async()=>{
  const query=queryFixture();query.conditions.providers.push({platform:'x',query:'indie'});query.sources={youtube:{status:'more',blocked_reason:'collection_disabled'},x:{status:'more'}};
  const {api}=start(query);await screen.findByText('Collection off');
  expect(screen.getByRole('button',{name:'Continue discovery'})).toBeEnabled();expect(screen.queryByText('No available sources')).not.toBeInTheDocument();
  expect(api.match.continueDiscovery).not.toHaveBeenCalled();
});
it('communicates bounded in-flight pause without pretending the running task stopped',async()=>{
  const {api}=start(queryFixture('running'));
  expect(await screen.findByText('Pauses after in-flight collection')).toBeVisible();
  expect(screen.getByRole('button',{name:'Stop discovery'})).toBeVisible();expect(api.match.stop).not.toHaveBeenCalled();
});
it('keeps new-search inputs usable while no selected channel is eligible',async()=>{
  const {api,user}=start();await screen.findByText('No available sources');
  await user.click(screen.getByRole('button',{name:'Adjust conditions'}));
  const find=screen.getByRole('button',{name:'Find creators'});expect(find).toBeDisabled();
  await user.click(screen.getByRole('checkbox',{name:/^X$/}));expect(find).toBeEnabled();
  expect(api.match.createPlan).not.toHaveBeenCalled();
});
