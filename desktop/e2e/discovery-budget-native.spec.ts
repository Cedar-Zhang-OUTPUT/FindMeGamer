import {test, expect, type ElectronApplication} from '@playwright/test';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {isAbsolute, join} from 'node:path';
import {tmpdir} from 'node:os';
import {launchElectronTarget, electronTargetEvidence} from './electron-target';
import {isolatedPreferences} from './preferences';

interface Fixture {
  synthetic: true; base_url: string; workspace_key: string;
  queries: Array<{id: string; activity_id: string; max_requests: 2 | 3}>;
}
test.use({trace: 'off', screenshot: 'off', video: 'off'});
test('packaged real IPC reads provider budgets three and legacy two without HTTP writes', async ({}, info) => {
  test.skip(process.env.FMG_DISCOVERY_BUDGET_NATIVE !== '1', 'Explicit isolated read-only fixture required.');
  test.setTimeout(60_000);
  const manifest = process.env.FMG_DISCOVERY_BUDGET_FIXTURE;
  if (!manifest || !isAbsolute(manifest) || !process.env.FMG_PACKAGED_EXECUTABLE) throw Error('explicit_fixture_and_package_required');
  const fixture = JSON.parse(await readFile(manifest, 'utf8')) as Fixture;
  const origin = new URL(fixture.base_url);
  const uuid = (id: unknown) => typeof id === 'string' && /^[a-f\d]{8}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{4}-[a-f\d]{12}$/i.test(id);
  if (fixture.synthetic !== true || origin.protocol !== 'http:' || origin.hostname !== '127.0.0.1' || !origin.port
    || origin.username || origin.password || origin.pathname !== '/' || origin.search || origin.hash
    || typeof fixture.workspace_key !== 'string' || !fixture.workspace_key
    || !Array.isArray(fixture.queries) || fixture.queries.length !== 2
    || ![2, 3].every(n => fixture.queries.some(q => q.max_requests === n))
    || fixture.queries.some(q => !uuid(q.id) || !uuid(q.activity_id))) throw Error('invalid_fixture');
  const userData = await mkdtemp(join(tmpdir(), 'fmg-budget12-'));
  await isolatedPreferences(userData);
  const env = Object.fromEntries(Object.entries(process.env).filter(([key, value]) => value !== undefined
    && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string, string>;
  let app: ElectronApplication | undefined;
  try {
    app = await launchElectronTarget(userData, env);
    const target = await electronTargetEvidence(app);
    expect(target.packaged).toBe(true);
    await app.evaluate(({session}, allowedOrigin) => {
      (globalThis as any).__budgetTraffic = [];
      for (const name of ['workspace-network', 'renderer', 'updates-network']) {
        session.fromPartition(name).webRequest.onBeforeRequest((details, callback) => {
          if (!/^https?:/.test(details.url)) { callback({cancel: false}); return; }
          const url = new URL(details.url), allowed = details.method === 'GET' && url.origin === allowedOrigin;
          (globalThis as any).__budgetTraffic.push({method: details.method, path: url.pathname, allowed});
          callback({cancel: !allowed});
        });
      }
    }, origin.origin);
    const page = await app.firstWindow();
    page.setDefaultTimeout(12_000);
    let pageErrors = 0; page.on('pageerror', () => pageErrors++);
    await page.getByRole('button', {name: 'Open Settings', exact: true}).click();
    await page.getByLabel('Service URL').fill(origin.origin);
    try { await page.getByLabel('Workspace key', {exact: true}).fill(fixture.workspace_key); }
    catch { throw Error('synthetic_credential_entry_failed'); }
    await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await expect(page.getByText('Connection verified', {exact: true})).toBeVisible();
    const read = () => page.evaluate(async queries => {
      const rows = [];
      for (const q of queries) {
        const query = await window.desktop.match.query(q.id);
        const activity = await window.desktop.match.activity(q.activity_id);
        if (!query.ok || !activity.ok) throw Error('budget_query_decode_failed');
        const nested = activity.data.queries.find(row => row.id === q.id);
        rows.push({id: q.id, direct: query.data.conditions.providers.find(p => p.platform === 'youtube')?.max_requests,
          nested: nested?.conditions.providers.find(p => p.platform === 'youtube')?.max_requests,
          used: query.data.usage.requests_used});
      }
      return rows;
    }, fixture.queries);
    const before = await read();
    for (const [i, q] of fixture.queries.entries()) expect(before[i]).toMatchObject({id: q.id, direct: q.max_requests, nested: q.max_requests});
    await page.reload(); await page.waitForFunction(() => Boolean(window.desktop?.match));
    expect(await read()).toEqual(before);
    const traffic = await app.evaluate(() => (globalThis as any).__budgetTraffic) as Array<{method: string; path: string; allowed: boolean}>;
    expect(traffic.every(row => row.method === 'GET' && row.allowed)).toBe(true);
    expect(pageErrors).toBe(0);
    await writeFile(info.outputPath('verification.json'), JSON.stringify({target, userData, realIPC: true, reads: before, reload: true, httpWrites: 0, pageErrors, traffic}, null, 2));
  } finally { await app?.close(); }
});
