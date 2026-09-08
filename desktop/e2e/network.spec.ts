import { test, expect, _electron as electron, type ElectronApplication } from '@playwright/test';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { isolatedPreferences } from './preferences';

test.use({trace:'off'});
test('system-proxy HTTPS works without shell proxy variables or credentials', async () => {
  test.skip(process.env.FMG_VERIFY_SYSTEM_HTTPS !== '1', 'Explicit opt-in for a read-only public health request.');
  const userData = await mkdtemp(path.join(tmpdir(),'fmg-proxy-e2e-'));
  await isolatedPreferences(userData);
  let app: ElectronApplication | undefined;
  try {
    const env = Object.fromEntries(Object.entries(process.env).filter(([name,value]) => value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(name))) as Record<string,string>;
    const executablePath = process.env.FMG_PACKAGED_EXECUTABLE;
    app = await electron.launch({args:[...(executablePath ? [] : ['.']),`--user-data-dir=${userData}`],...(executablePath ? {executablePath} : {}),cwd:process.cwd(),env,chromiumSandbox:true});
    if (executablePath) expect(await app.evaluate(({app}) => app.isPackaged)).toBe(true);
    await (await app.firstWindow()).getByRole('heading',{name:'Connect your workspace'}).waitFor();
    const result = await app.evaluate(async ({session}) => {
      const network = session.fromPartition('workspace-network');
      const target = 'https://44.233.174.193/health/live';
      const route = await network.resolveProxy(target);
      const response = await network.fetch(target,{redirect:'error',credentials:'omit',signal:AbortSignal.timeout(20_000)});
      const body = await response.json();
      return {proxy:route !== 'DIRECT',status:response.status,healthy:body.status === 'ok',shellProxyPresent:Object.keys(process.env).some(key => /^(https?_proxy|all_proxy)$/i.test(key))};
    });
    expect(result.status).toBe(200);
    expect(result.healthy).toBe(true);
    expect(result.shellProxyPresent).toBe(false);
    // This machine has an enabled macOS system HTTP(S) proxy; no route credentials are logged.
    expect(result.proxy).toBe(true);
  } finally { await app?.close(); await rm(userData,{recursive:true,force:true}); }
});
