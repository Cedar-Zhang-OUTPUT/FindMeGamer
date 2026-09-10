import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { createServer } from 'node:http';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { CreatorDetail, CreatorPage, WorkPage } from '../src/shared/creators';
import { isolatedPreferences } from './preferences';

// Synthetic records only in the fixed integration workspace. Never capture keys.
test.use({ trace:'off', screenshot:'off', video:'off' });
test('Creator edits, contacts, known works and identity history survive real API writes and interrupted responses',async()=>{
  test.setTimeout(120_000);
  const file=process.env.FMG_BACKEND_FIXTURE_FILE;
  test.skip(!file,'Requires the authorized isolated Creator API.');if(!file)return;
  expect((await stat(file)).mode&0o077).toBe(0);
  const fixture=JSON.parse(await readFile(file,'utf8')) as {base_url:string;workspace_key:string};
  expect(new URL(fixture.base_url).origin).toBe('http://127.0.0.1:18090');
  async function api<T>(route:string,method='GET',body?:unknown):Promise<T>{
    const response=await fetch(`${fixture.base_url}${route}`,{method,headers:{Authorization:`Bearer ${fixture.workspace_key}`,'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    if(!response.ok)throw Error(`Isolated Creator API failed (HTTP ${response.status}).`);return response.json() as Promise<T>;
  }
  const attempts=new Map<string,{key:string;body:string}[]>();const createdIds:string[]=[];const dropped=new Set<string>();let dropIdentity=true;
  const relay=createServer(async(request,response)=>{
    const route=new URL(request.url!,'http://localhost');
    if(!/^\/api\/(v1\/session|v2\/library\/(creators(?:\/[0-9a-f-]+(?:\/(?:contacts|works)(?:\/[0-9a-f-]+)?|\/identity)?)?|games(?:\/[0-9a-f-]+)?))$/.test(route.pathname)){response.writeHead(404).end();return;}
    try{
      const chunks:Buffer[]=[];for await(const chunk of request)chunks.push(Buffer.from(chunk));const body=Buffer.concat(chunks).toString('utf8');
      const headers:Record<string,string>={Authorization:request.headers.authorization??'','Content-Type':'application/json'};
      if(typeof request.headers['idempotency-key']==='string')headers['Idempotency-Key']=request.headers['idempotency-key'];
      if(request.method==='POST'){const calls=attempts.get(route.pathname)??[];calls.push({key:headers['Idempotency-Key'],body});attempts.set(route.pathname,calls);}
      const upstream=await fetch(`${fixture.base_url}${route.pathname}${route.search}`,{method:request.method,headers,...(body?{body}:{})});const output=await upstream.text();
      if(upstream.status===201&&request.method==='POST'&&route.pathname==='/api/v2/library/creators')createdIds.push((JSON.parse(output) as CreatorDetail).id);
      if(upstream.status===201&&request.method==='POST'&&!dropped.has(route.pathname)){dropped.add(route.pathname);response.writeHead(502,{'Content-Type':'application/json'}).end('{}');return;}
      if(upstream.ok&&request.method==='PUT'&&route.pathname.endsWith('/identity')&&dropIdentity){dropIdentity=false;response.writeHead(502,{'Content-Type':'application/json'}).end('{}');return;}
      response.writeHead(upstream.status,{'Content-Type':'application/json'}).end(output);
    }catch{response.writeHead(502,{'Content-Type':'application/json'}).end('{}');}
  });
  await new Promise<void>(resolve=>relay.listen(0,'127.0.0.1',resolve));
  const origin=`http://127.0.0.1:${(relay.address() as {port:number}).port}`;
  const userData=await mkdtemp(path.join(tmpdir(),'fmg-creator-v2-e2e-'));await isolatedPreferences(userData);
  const suffix=randomUUID().slice(0,8),name=`Desktop Creator Test ${suffix}`,email=`${suffix}@example.com`;
  let app:ElectronApplication|undefined;
  try{
    const env=Object.fromEntries(Object.entries(process.env).filter(([name,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string,string>;
    const executablePath=process.env.FMG_PACKAGED_EXECUTABLE;
    app=await electron.launch({args:[...(executablePath?[]:['.']),`--user-data-dir=${userData}`],...(executablePath?{executablePath}:{}),cwd:process.cwd(),env,chromiumSandbox:true});
    const page=await app.firstWindow();let pageErrors=0;page.on('pageerror',()=>pageErrors++);
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(origin);
    try{await page.getByLabel('Workspace key',{exact:true}).fill(fixture.workspace_key);}catch{throw Error('Test credential entry failed; details suppressed.');}
    await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible();
    await page.getByRole('button',{name:'Library',exact:true}).click();await page.getByRole('button',{name:'New creator',exact:true}).click();
    await page.getByLabel('Account ID',{exact:true}).fill(`UC_test_${suffix}`);await page.getByLabel('Name',{exact:true}).fill(name);
    await page.getByRole('button',{name:'Create creator',exact:true}).click();await expect(page.getByLabel('Name',{exact:true})).toBeDisabled();
    await page.getByRole('button',{name:'Retry same request',exact:true}).click();await expect(page.getByRole('heading',{name,exact:true})).toBeVisible();
    expect(createdIds).toHaveLength(2);expect(createdIds[1]).toBe(createdIds[0]);
    const id=createdIds[0],route=`/api/v2/library/creators/${id}`;
    const current=()=>api<CreatorDetail>(route);
    await page.getByRole('button',{name:'Edit profile',exact:true}).click();await page.getByLabel('Name',{exact:true}).fill(`${name} edited`);
    await page.getByRole('button',{name:'Settings',exact:true}).click();await expect(page.getByRole('dialog',{name:'Unsaved creator changes'})).toBeVisible();await page.keyboard.press('Escape');
    expect(await page.getByLabel('Name',{exact:true}).inputValue()).toBe(`${name} edited`);
    const initial=await current();await api(route,'PATCH',{expected_revision:initial.revision,name:`${name} remote`,description:'Remote description retained.'});
    await page.getByRole('button',{name:'Save changes',exact:true}).click();await page.getByRole('radio',{name:'Keep mine: Name',exact:true}).check();await page.getByRole('button',{name:'Apply choices',exact:true}).click();await page.getByRole('button',{name:'Save changes',exact:true}).click();
    await expect(page.getByRole('heading',{name:`${name} edited`,exact:true})).toBeVisible();expect((await current()).description).toBe('Remote description retained.');
    for(const publicName of ['First public name','Reconfirmed public name']){
      await page.getByRole('button',{name:'Edit profile',exact:true}).click();await page.getByText('Display details',{exact:true}).click();await page.getByLabel('Public name',{exact:true}).fill(publicName);await page.getByLabel('Public name confirmed',{exact:true}).check();await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByRole('button',{name:'Edit profile',exact:true})).toBeVisible();expect(await current()).toMatchObject({public_name:publicName,public_name_confirmed:true});
    }
    await page.getByRole('button', { name: 'Emails',exact:true}).click();await page.getByRole('button',{name:'Add email',exact:true}).click();await page.getByRole('textbox',{name:'Email',exact:true}).fill(email);await page.getByLabel('Purpose',{exact:true}).fill('Business');await page.getByRole('button',{name:'Add email',exact:true}).click();await page.getByRole('button',{name:'Retry same request',exact:true}).click();
    await expect(page.getByRole('heading',{name:email,exact:true})).toBeVisible();const contact=(await current()).contacts.find(item=>item.email===email)!;expect(contact.is_active).toBe(true);
    const second=`second-${email}`;await page.getByRole('button',{name:'Add email',exact:true}).click();await page.getByRole('textbox',{name:'Email',exact:true}).fill(second);await page.getByRole('button',{name:'Add email',exact:true}).click();await page.getByRole('button',{name:`Edit ${second}`,exact:true}).click();await page.getByLabel('Active',{exact:true}).uncheck();await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByRole('button',{name:`Edit or restore ${second}`,exact:true})).toBeVisible();expect((await current()).contacts.find(item=>item.email===second)?.is_active).toBe(false);
    await page.getByRole('button', { name: 'Known works',exact:true}).click();await page.getByRole('button',{name:'Add work',exact:true}).click();await page.getByLabel('Work name',{exact:true}).fill('Recorded gameplay');await page.getByLabel('Content type',{exact:true}).selectOption('gameplay');await page.getByRole('button',{name:'Add work',exact:true}).click();await page.getByRole('button',{name:'Retry same request',exact:true}).click();
    await expect(page.getByRole('heading',{name:'Recorded gameplay',exact:true})).toBeVisible();const works=await api<WorkPage>(`${route}/works`);expect(works.items).toHaveLength(1);expect((await current()).work_count).toBe(1);
    await page.getByRole('button',{name:'Edit Recorded gameplay',exact:true}).click();await page.getByLabel('Work name',{exact:true}).fill('Edited gameplay');await page.getByRole('button',{name:'Save changes',exact:true}).click();await expect(page.getByRole('heading',{name:'Edited gameplay',exact:true})).toBeVisible();expect((await api<WorkPage>(`${route}/works`)).items[0].revision).toBe(works.items[0].revision+1);
    await page.getByRole('tab',{name:'Profile',exact:true}).click();await page.getByText('Account identity',{exact:true}).click();await page.getByRole('button',{name:'Change identity',exact:true}).click();await page.getByLabel('New account ID',{exact:true}).fill(`UC_rebound_${suffix}`);await page.getByRole('button',{name:'Review identity change',exact:true}).click();await page.keyboard.press('Escape');await expect(page.getByLabel('New account ID',{exact:true})).toHaveValue(`UC_rebound_${suffix}`);
    await page.getByRole('button',{name:'Review identity change',exact:true}).click();await page.getByRole('button',{name:'Change identity',exact:true}).click();await page.getByRole('button',{name:'Check current identity',exact:true}).click();await page.getByRole('button',{name:'Use current account',exact:true}).click();
    await expect(page.getByRole('button',{name:'Edit profile',exact:true})).toBeVisible();const rebound=await current();expect(rebound.source_identity.account_id).toBe(`UC_rebound_${suffix}`);expect(rebound.contacts.every(item=>!item.is_current_identity&&!item.is_active)).toBe(true);
    await page.getByRole('button', { name: 'Emails',exact:true}).click();await expect(page.getByRole('button',{name:`Edit ${email}`,exact:true})).toHaveCount(0);await expect(page.getByRole('heading',{name:email,exact:true})).toBeVisible();
    await page.getByRole('button', { name: 'Known works',exact:true}).click();await expect(page.getByRole('heading',{name:'No known works',exact:true})).toBeVisible();await page.getByLabel('Include previous identities',{exact:true}).check();await expect(page.getByRole('heading',{name:'Edited gameplay',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Edit Edited gameplay',exact:true})).toHaveCount(0);
    for(const suffix of ['', '/contacts','/works']){const calls=attempts.get(suffix?`${route}${suffix}`:'/api/v2/library/creators')!;expect(calls.length).toBeGreaterThanOrEqual(2);expect(calls[1]).toEqual(calls[0]);}
    expect(pageErrors).toBe(0);expect((await readFile(path.join(userData,'credentials.json'),'utf8')).includes(fixture.workspace_key)).toBe(false);
    // List/search acceptance remains mandatory, but a server failure must not
    // prevent the rest of the independent write/readback checks from running.
    const list=await api<CreatorPage>(`/api/v2/library/creators?query=${encodeURIComponent(name)}`);expect(list.items.filter(item=>item.id===id)).toHaveLength(1);
  }finally{await app?.close();await new Promise<void>(resolve=>relay.close(()=>resolve()));await rm(userData,{recursive:true,force:true});}
});
