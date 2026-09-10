import {_electron as electron,type ElectronApplication} from '@playwright/test';
import {readFile} from 'node:fs/promises';
import {isAbsolute} from 'node:path';

/** Explicit packaged target only; never discover/replace the user's installed app. */
export async function launchElectronTarget(userData:string,env:Record<string,string>):Promise<ElectronApplication>{
 const executable=process.env.FMG_PACKAGED_EXECUTABLE;
 if(executable&&(!isAbsolute(executable)||!executable.endsWith('/FindMeGamer.app/Contents/MacOS/FindMeGamer')))throw Error('explicit_package_executable_required');
 const app=await electron.launch(executable?{executablePath:executable,args:[`--user-data-dir=${userData}`],env,chromiumSandbox:true}:{args:['.',`--user-data-dir=${userData}`],cwd:process.cwd(),env,chromiumSandbox:true});
 const target=await app.evaluate(({app})=>({packaged:app.isPackaged,version:app.getVersion()}));
 const expected=JSON.parse(await readFile('package.json','utf8')).version;
 if(target.packaged!==Boolean(executable)||target.version!==expected){await app.close();throw Error('electron_target_mismatch');}
 return app;
}
export async function electronTargetEvidence(app:ElectronApplication){return app.evaluate(({app})=>({packaged:app.isPackaged,version:app.getVersion(),appPath:app.getAppPath(),pid:process.pid}));}
