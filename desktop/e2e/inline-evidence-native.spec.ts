import { test, expect, type ElectronApplication } from '@playwright/test';
import { mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { join, isAbsolute } from 'node:path';
import { tmpdir } from 'node:os';
import { launchElectronTarget, electronTargetEvidence } from './electron-target';
import { isolatedPreferences } from './preferences';

type Case = { case: string; creator_id: string; selection_id: string; work_id: string; draft_id: string };
type Fixture = { synthetic: true; base_url: string; workspace_key: string; activity_id: string; composition_id: string; cases: Case[]; write_allowlist: {method: string;path: string}[] };
test.use({ trace: 'off', screenshot: 'off', video: 'off' });
test('packaged inline evidence preserves generated, unsaved and partial wording with zero dispatch and send', async ({}, info) => {
  test.skip(process.env.FMG_INLINE_EVIDENCE_NATIVE !== '1', 'Explicit isolated fixture required');
  test.setTimeout(90_000);
  const manifest = process.env.FMG_INLINE_EVIDENCE_FIXTURE;
  if (!manifest || !isAbsolute(manifest) || !process.env.FMG_PACKAGED_EXECUTABLE) throw Error('explicit_fixture_and_package_required');
  const f = JSON.parse(await readFile(manifest, 'utf8')) as Fixture;
  const origin = new URL(f.base_url);
  if (f.synthetic !== true || origin.hostname !== '127.0.0.1' || origin.protocol !== 'http:' || !origin.port || f.cases.length !== 3) throw Error('invalid_fixture');
  const userData = await mkdtemp(join(tmpdir(), 'fmg-inline-evidence-'));
  await isolatedPreferences(userData);
  const env = Object.fromEntries(Object.entries(process.env).filter(([key,value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
  let app: ElectronApplication | undefined;
  try {
    app = await launchElectronTarget(userData, env);
    const target = await electronTargetEvidence(app);
    expect(target.packaged).toBe(true);
    await app.evaluate(({session,BrowserWindow},scope) => {
      BrowserWindow.getAllWindows()[0].setSize(1440,1000);
      const audit: {method:string;path:string;allowed:boolean}[]=[];
      (globalThis as any).__evidenceTraffic=audit;
      for(const partition of ['workspace-network','renderer','updates-network']) session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
        if(!/^https?:/.test(details.url)){callback({cancel:false});return;}
        const url=new URL(details.url),allowed=url.origin===scope.origin&&(details.method==='GET'||scope.writes.some(row=>row.method===details.method&&row.path===url.pathname));
        audit.push({method:details.method,path:url.pathname,allowed});callback({cancel:!allowed});
      });
    },{origin:origin.origin,writes:f.write_allowlist});
    const page=await app.firstWindow();page.setDefaultTimeout(12000);
    page.on('pageerror',error=>console.log('Renderer error:',error.message.replaceAll(f.workspace_key,'[redacted]')));
    await page.emulateMedia({reducedMotion:'reduce'});
    try { await page.getByRole('button',{name:'Open Settings',exact:true}).click(); }
    catch { await page.screenshot({path:info.outputPath('startup-failure.png')});throw Error('startup_settings_control_unavailable'); }
    await page.getByLabel('Service URL').fill(f.base_url);
    try{await page.getByLabel('Workspace key',{exact:true}).fill(f.workspace_key);}catch{throw Error('fixture_credential_entry_failed');}
    await page.getByRole('button',{name:'Connect',exact:true}).click();
    await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    const metadataChecks:unknown[]=[];
    if(process.env.FMG_WORK_METADATA_NATIVE==='1'){
      for(const scenario of f.cases){
        const data=await page.evaluate(async creatorId=>{const result=await window.desktop.creators.works({creatorId,limit:100,offset:0});if(!result.ok)throw Error('metadata_works_decode_failed');return result.data;},scenario.creator_id);
        const work=data.items.find(row=>row.id===scenario.work_id);expect(work).toBeTruthy();
        const metadata=work!.source_fields.outreach_observation as Record<string,unknown>;
        expect(Object.keys(metadata).sort()).toEqual(['evidence_kind','excerpt','source_field','source_url','text']);
        expect(metadata.evidence_kind).toBe('metadata');
        metadataChecks.push({creatorId:scenario.creator_id,workId:work!.id,keys:Object.keys(metadata),evidence_kind:metadata.evidence_kind});
      }
      const creator=await page.evaluate(async id=>{const r=await window.desktop.creators.detail(id);if(!r.ok)throw Error('metadata_creator_read_failed');return r.data;},f.cases[0].creator_id);
      await page.getByRole('button',{name:'Library',exact:true}).click();
      await page.getByRole('table',{name:'Creators',exact:true}).getByRole('button',{name:`Open ${creator.name}`,exact:true}).click();
      await page.getByRole('button',{name:'Known works',exact:true}).click();
      await expect(page.locator('.creator-work-list').getByRole('heading').first()).toBeVisible();
      await expect(page.getByText(/unsupported Creator response/)).toHaveCount(0);
      await page.screenshot({path:info.outputPath('creator-works-metadata.png')});
    }
    const read=()=>page.evaluate(async id=>{const r=await window.desktop.drafts.composition(id);if(!r.ok)throw Error('composition_read_failed');return r.data;},f.composition_id);
    async function open(){
      await page.getByRole('button',{name:'Match',exact:true}).click();
      await page.getByRole('list',{name:'Activities',exact:true}).locator(`button[data-activity-id="${f.activity_id}"]`).click();
      const ids=await page.evaluate(async activityId=>{const r=await window.desktop.drafts.compositions({activityId,offset:0,limit:50});if(!r.ok)throw Error('history_read_failed');return r.data.items.map(row=>row.id);},f.activity_id);
      await page.getByText('History & saved lists',{exact:true}).click();
      await page.getByRole('button',{name:'Draft history',exact:true}).click();
      await page.getByRole('button',{name:'Open draft set',exact:true}).nth(ids.indexOf(f.composition_id)).click();
      await page.getByText('History & saved lists',{exact:true}).click();
    }
    await open();
    await page.screenshot({path:info.outputPath('draft-set-opened.png')});
    const labels={firstName:'Public name',channelName:'Channel name',reference:'Referenced work',observation:'Observation'};
    const results:unknown[]=[];
    for(const scenario of f.cases){
      console.log('Native evidence case',scenario.case,'read');
      const before=await read(),index=before.drafts.findIndex(row=>row.id===scenario.draft_id),original=before.drafts[index];
      expect(['pending','running']).not.toContain(original.status);
      try { await page.getByRole('navigation',{name:'Draft people'}).getByRole('button').nth(index).click(); }
      catch { await page.screenshot({path:info.outputPath('draft-load-failure.png')});
        const batchResult=await page.evaluate(async scope=>{const r=await window.desktop.outreach.batch(scope);return r.ok?{ok:true}:r;},{activityId:f.activity_id,id:before.recipient_batch_id});
        console.log('Batch read result',batchResult);throw Error('draft_people_unavailable'); }
      const editor=page.getByRole('region',{name:'Draft email editor',exact:true});
      console.log('Native evidence case',scenario.case,'editor');
      const toggle=editor.getByRole('button',{name:'Edit personalization',exact:true});
      if(await toggle.getAttribute('aria-expanded')==='false')await toggle.click();
      const wording={...original.values!};
      if(scenario.case==='unsaved_buffer_target')Object.assign(wording,{firstName:'Synthetic unsaved greeting',channelName:'Synthetic unsaved channel',reference:'Synthetic unsaved reference',observation:'Synthetic unsaved observation.'});
      if(scenario.case==='partial_no_selected_work')Object.assign(wording,{firstName:'',observation:''});
      for(const key of Object.keys(labels) as (keyof typeof labels)[])await editor.getByLabel(labels[key],{exact:true}).fill(wording[key]??'');
      const evidence=editor.getByRole('region',{name:'Shared work evidence'});
      const select=evidence.getByRole('combobox',{name:'Source work'});
      try{await expect(select).toBeVisible();}catch{
        await page.screenshot({path:info.outputPath('evidence-load-failure.png')});
        console.log('Evidence state',await evidence.innerText());throw Error('inline_evidence_unavailable');
      }
      if(await select.inputValue()!==scenario.work_id)await select.selectOption(scenario.work_id);
      const suffix=`${Date.now()}-${scenario.case}`;
      const excerpt=`Synthetic recorded scene ${suffix}`,notes=`Synthetic source verification ${suffix}`,url='https://example.test/recorded-work';
      await evidence.getByLabel('Evidence excerpt',{exact:true}).fill(excerpt);
      await evidence.getByLabel('Verification notes',{exact:true}).fill(notes);
      await evidence.getByLabel('Source URL',{exact:true}).fill(url);
      console.log('Native evidence case',scenario.case,'input');
      if(scenario.case==='unsaved_buffer_target'){
        const fail=await fetch(`${f.base_url}/__fixture/fail-next-work-patch`,{method:'POST',headers:{Authorization:`Bearer ${f.workspace_key}`}});
        expect(fail.ok).toBe(true);
        await evidence.getByRole('button',{name:'Save evidence & draft',exact:true}).click();
        await expect(evidence.getByText(/Save stopped/)).toBeVisible();
        await expect(evidence.getByLabel('Evidence excerpt',{exact:true})).toHaveValue(excerpt);
        await expect(editor.getByLabel('Observation',{exact:true})).toHaveValue(wording.observation);
        expect((await read()).drafts[index].revision).toBe(original.revision);
        await evidence.getByRole('button',{name:'Reload evidence',exact:true}).click();
        await expect(evidence.getByText(/Current evidence loaded/)).toBeVisible();
      }
      await evidence.getByRole('button',{name:'Save evidence & draft',exact:true}).click();
      console.log('Native evidence case',scenario.case,'save requested');
      await expect(evidence.getByText('Evidence and draft saved · wording retained',{exact:true})).toBeVisible();
      console.log('Native evidence case',scenario.case,'saved');
      const after=await read(),draft=after.drafts[index];
      expect(draft.values).toEqual(wording);expect(draft.revision).toBe(original.revision+1);
      expect(draft.input.work).toMatchObject({id:scenario.work_id,evidence_excerpt:excerpt,verification_notes:notes,source_url:url});
      expect(draft.source_changed).toBe(false);expect(draft.sender_facts).toEqual({});expect(draft.sender_facts_valid).toBe(false);expect(draft.send_ready).toBe(false);
      expect(after.drafts.filter(row=>row.id!==draft.id)).toEqual(before.drafts.filter(row=>row.id!==draft.id));
      results.push({case:scenario.case,revision:draft.revision,status:draft.status,wording_retained:true,source_updated:true});
      await editor.getByLabel('Observation',{exact:true}).scrollIntoViewIfNeeded();
      await page.screenshot({path:info.outputPath(`${scenario.case}.png`)});
    }
    const final=await read();await page.reload();await page.waitForFunction(()=>!!window.desktop?.drafts);expect(await read()).toEqual(final);
    await open();
    const statusResponse=await fetch(`${f.base_url}/__fixture/status`,{headers:{Authorization:`Bearer ${f.workspace_key}`}});
    const status=await statusResponse.json();
    expect(status.dispatch_attempts).toBe(0);expect(status.send_attempts).toBe(0);expect(status.real_provider_calls).toBe(0);
    const traffic=await app.evaluate(()=> (globalThis as any).__evidenceTraffic);
    expect(traffic.filter((r:any)=>!r.allowed)).toEqual([]);
    await writeFile(info.outputPath('evidence.json'),JSON.stringify({target,results,status,traffic,metadataChecks,reload_persisted:true},null,2));
  } finally {if(app){await app.evaluate(({app})=>app.exit(0)).catch(()=>{});}}
});
