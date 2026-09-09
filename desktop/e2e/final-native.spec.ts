import {test,expect,_electron as electron,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile,stat} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';
test.use({trace:'off',screenshot:'off',video:'off'});
test('final isolated packaged Electron startup and read-only Library IPC',async({},info)=>{
 test.skip(process.env.FMG_FINAL_NATIVE!=='64692','Single coordinator-authorized native attempt only.');test.setTimeout(70_000);
 const executable=process.env.FMG_PACKAGED_EXECUTABLE;
 if(!executable?.startsWith('/tmp/fmg-final-app-fcbc760-')||!executable.endsWith('/FindMeGamer.app/Contents/MacOS/FindMeGamer'))throw Error('explicit_final_package_required');
 const privateRoot='/var/folders/p4/5cgpbz2n2hj98xdvs3_b1hlc0000gn/T/fmg-match-frontend-xmmhoufp/private';
 const file=privateRoot+'/client.json';expect((await stat(file)).mode&0o077).toBe(0);const fixture=JSON.parse(await readFile(file,'utf8'));
 expect(fixture.base_url).toBe('http://127.0.0.1:64692');expect(fixture.backend_revision).toBe('5706ad76f924991b80ee2a7fb6806528366be5ce');
 const userData=await mkdtemp('/tmp/fmg-final-native-profile-');await isolatedPreferences(userData);
 const ledger=userData+'/native-verification.json';const report:Record<string,unknown>={status:'running',stage:'launch',executable,userData,source:'fcbc7603088d2c2765b43649e06152ff23587a78',native:true};
 async function checkpoint(stage:string){report.stage=stage;await writeFile(ledger,JSON.stringify(report,null,2),{mode:0o600});console.log(JSON.stringify({stage,ledger,pid:report.pid}));}
 let app:ElectronApplication|undefined;
 try{
  await checkpoint('launch');const env=Object.fromEntries(Object.entries(process.env).filter(([name,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string,string>;
  app=await electron.launch({executablePath:executable,args:[`--user-data-dir=${userData}`],env,chromiumSandbox:true,timeout:20_000});report.pid=app.process().pid;
  report.main=await app.evaluate(({app,BrowserWindow,session})=>{
   const traffic:{method:string;url:string;blocked:boolean}[]=[];(globalThis as any).__nativeTraffic=traffic;
   for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{const url=new URL(details.url);const allowed=url.protocol==='fmg:'||url.protocol==='data:'||url.protocol==='about:'||(partition==='workspace-network'&&url.origin==='http://127.0.0.1:64692'&&details.method==='GET');if(url.protocol==='http:'||url.protocol==='https:')traffic.push({method:details.method,url:url.pathname,blocked:!allowed});callback({cancel:!allowed});});
   return {packaged:app.isPackaged,path:app.getAppPath(),windows:BrowserWindow.getAllWindows().length};
  });expect(report.main).toMatchObject({packaged:true,path:expect.stringContaining('app.asar')});await checkpoint('first_window');
  const page=await app.firstWindow({timeout:25_000});await checkpoint('connect_screen');await expect(page.getByRole('heading',{name:'Connect your workspace'})).toBeVisible({timeout:12_000});
  report.preload=await page.evaluate(()=>({url:location.href,node:typeof (window as any).require,process:typeof (window as any).process,methods:Object.keys(window.desktop).sort(),analysis:typeof window.desktop.analysis.detail}));expect(report.preload).toMatchObject({url:'fmg://app/index.html',node:'undefined',process:'undefined',analysis:'function'});
  await page.getByRole('button',{name:'Open Settings',exact:true}).click();await page.getByLabel('Service URL').fill(fixture.base_url);await checkpoint('keychain_save');
  try{await page.getByLabel('Workspace key',{exact:true}).fill(fixture.workspace_key);}catch{throw Error('credential_entry_failed');}
  await page.getByRole('button',{name:'Connect',exact:true}).click();await expect(page.getByText('Connection verified',{exact:true})).toBeVisible({timeout:12_000});await expect(page.getByLabel('Workspace key',{exact:true})).toHaveValue('');
  await checkpoint('library_reads');await page.getByRole('button',{name:'Library',exact:true}).click();await page.getByRole('searchbox',{name:'Search creators'}).fill('Human X name');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('button',{name:'Open Human X name',exact:true}).click();await expect(page.getByText(/21 recent original posts/)).toBeVisible();
  await page.getByRole('button',{name:'Analysis tasks',exact:true}).click();await expect(page.getByRole('dialog',{name:'Analysis'}).locator('.analysis-task').first()).toBeVisible();await page.keyboard.press('Escape');
  await page.getByRole('tab',{name:'Games',exact:true}).click();await page.getByRole('searchbox',{name:'Search games'}).fill('Human Station');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('button',{name:'Open Human Station',exact:true}).click();await expect(page.getByRole('heading',{name:'Human Station'})).toBeVisible();
  await page.getByText('Game analysis',{exact:true}).click();await expect(page.getByRole('region',{name:'Analysis insights'})).toBeVisible();const screenshot=info.outputPath('native-game-analysis.png');await page.screenshot({path:screenshot});report.screenshot=screenshot;
  const stored=await readFile(userData+'/credentials.json','utf8');expect(stored.includes(fixture.workspace_key)).toBe(false);report.encryptedCredential=true;
  report.traffic=await app.evaluate(()=> (globalThis as any).__nativeTraffic);expect((report.traffic as {method:string;blocked:boolean}[]).every(row=>row.method==='GET')).toBe(true);report.status='passed';await checkpoint('complete');
 }catch{report.status='blocked_or_failed';await checkpoint(String(report.stage));}
 finally{if(app){try{await Promise.race([app.close(),new Promise((_,reject)=>setTimeout(()=>reject(Error('close_timeout')),5000))]);}catch{report.closeTimedOut=true;}}await writeFile(ledger,JSON.stringify(report,null,2),{mode:0o600});}
 expect(report.status,`Native stage ${report.stage}; public evidence ${ledger}`).toBe('passed');
});
