import {test,expect,_electron as electron,type ElectronApplication} from '@playwright/test';
import {mkdtemp,readFile,writeFile} from 'node:fs/promises';
import {isolatedPreferences} from './preferences';
test.use({trace:'off',screenshot:'off',video:'off'});
test('internal package shows first-run cloud origin without a key or connection',async({},info)=>{
 test.skip(process.env.FMG_INTERNAL_FIRST_RUN!=='approved','Explicit packaged first-run verification only.');
 const executable=process.env.FMG_PACKAGED_EXECUTABLE;
 if(!executable?.includes('/artifacts/FindMeGamer-Electron-0.2.0-internal.1-arm64-')||!executable.endsWith('/FindMeGamer.app/Contents/MacOS/FindMeGamer'))throw Error('explicit_internal_package_required');
 const userData=await mkdtemp('/tmp/fmg-internal-first-run-');await isolatedPreferences(userData);
 let app:ElectronApplication|undefined;
 try{
  const env=Object.fromEntries(Object.entries(process.env).filter(([key,value])=>value!==undefined&&!/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string,string>;
  app=await electron.launch({executablePath:executable,args:[`--user-data-dir=${userData}`],env,chromiumSandbox:true,timeout:20_000});
  const main=await app.evaluate(({app,session})=>{
   (globalThis as any).__firstRunNetwork=[];
   for(const partition of ['workspace-network','renderer','updates-network'])session.fromPartition(partition).webRequest.onBeforeRequest((details,callback)=>{
    const external=/^https?:/.test(details.url);if(external)(globalThis as any).__firstRunNetwork.push(details.method);callback({cancel:external});
   });
   return {packaged:app.isPackaged,path:app.getAppPath(),userData:app.getPath('userData')};
  });expect(main).toMatchObject({packaged:true,userData});
  const page=await app.firstWindow();await page.getByRole('button',{name:'Open Settings',exact:true}).click();
  await expect(page.getByLabel('Service URL')).toHaveValue('https://44.233.174.193');await expect(page.getByLabel('Workspace key',{exact:true})).toHaveValue('');await expect(page.getByRole('button',{name:'Connect',exact:true})).toBeDisabled();
  const status=await page.evaluate(()=>window.desktop.connection.status());expect(status).toMatchObject({ok:true,data:{hasKey:false,serviceUrl:'https://44.233.174.193'}});
  await expect(readFile(userData+'/credentials.json')).rejects.toMatchObject({code:'ENOENT'});
  const traffic=await app.evaluate(()=>(globalThis as any).__firstRunNetwork);expect(traffic).toEqual([]);
  const screenshot=info.outputPath('internal-first-run.png');await page.screenshot({path:screenshot});
  await writeFile(info.outputPath('first-run.json'),JSON.stringify({status:'passed',main,executable,userData,traffic,screenshot,native:true,keyEntered:false},null,2));
 }finally{await app?.close();}
});
