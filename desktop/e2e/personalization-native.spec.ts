import {test, expect, type ElectronApplication} from '@playwright/test';
import {mkdtemp, readFile, writeFile} from 'node:fs/promises';
import {isAbsolute, join} from 'node:path';
import {tmpdir} from 'node:os';
import {launchElectronTarget, electronTargetEvidence} from './electron-target';
import {isolatedPreferences} from './preferences';

// IDs must identify a dedicated synthetic fixture, with activity/composition in
// the first history page. No production config, IPC stubs or send calls.
interface FixtureConnection {
  synthetic: true;
  base_url: string;
  workspace_key: string;
  composition_id: string;
  activity_id: string;
  draft_id: string;
  sibling_draft_id: string;
  creator_id: string;
}

async function fixtureConnection(): Promise<FixtureConnection> {
  const path = process.env.FMG_PERSONALIZATION_FIXTURE;
  if (!path || !isAbsolute(path)) throw Error('explicit_synthetic_fixture_manifest_required');
  const config = JSON.parse(await readFile(path, 'utf8')) as FixtureConnection;
  const url = new URL(config.base_url);
  if (config.synthetic !== true || url.protocol !== 'http:' || url.hostname !== '127.0.0.1'
      || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash
      || typeof config.workspace_key !== 'string' || !config.workspace_key
      || [config.composition_id, config.activity_id, config.draft_id, config.sibling_draft_id, config.creator_id]
        .some(id => typeof id !== 'string' || !/^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i.test(id))
      || config.draft_id === config.sibling_draft_id) {
    throw Error('invalid_synthetic_fixture_manifest');
  }
  return {...config, base_url: url.origin};
}

test.use({trace: 'off', screenshot: 'off', video: 'off'});

test('packaged draft overrides and unfinished values persist without enabling sending', async ({}, info) => {
  test.skip(process.env.FMG_PERSONALIZATION_NATIVE !== '1', 'Explicit isolated personalization fixture required.');
  test.setTimeout(90_000);
  if (!process.env.FMG_PACKAGED_EXECUTABLE) throw Error('explicit_package_executable_required');
  const fixture = await fixtureConnection();
  const userData = await mkdtemp(join(tmpdir(), 'fmg-personalization-'));
  await isolatedPreferences(userData);
  const env = Object.fromEntries(Object.entries(process.env).filter(([key, value]) =>
    value !== undefined && !/^(https?_proxy|all_proxy|no_proxy|ELECTRON_RUN_AS_NODE)$/i.test(key))) as Record<string, string>;
  let app: ElectronApplication | undefined;
  try {
    app = await launchElectronTarget(userData, env);
    const target = await electronTargetEvidence(app);
    expect(target.packaged).toBe(true);
    await app.evaluate(({session, BrowserWindow}, scope) => {
      BrowserWindow.getAllWindows()[0].setSize(1440, 1000);
      const audit: Array<{method: string; path: string; allowed: boolean}> = [];
      (globalThis as any).__personalizationTraffic = audit;
      for (const partition of ['workspace-network', 'renderer', 'updates-network']) {
        session.fromPartition(partition).webRequest.onBeforeRequest((details, callback) => {
          if (!/^https?:/.test(details.url)) { callback({cancel: false}); return; }
          const url = new URL(details.url);
          const allowed = url.origin === scope.origin && (details.method === 'GET'
            || (details.method === 'PATCH' && url.pathname === scope.editPath)
            || (details.method === 'POST' && url.pathname === scope.refreshPath)
            || (details.method === 'POST' && url.pathname === scope.qualificationPath));
          // Do not record headers, request bodies, query strings or credentials.
          audit.push({method: details.method, path: url.pathname, allowed});
          callback({cancel: !allowed});
        });
      }
    }, {origin: fixture.base_url, editPath: `/api/v2/outreach/drafts/${fixture.draft_id}`, refreshPath: `/api/v2/outreach/drafts/${fixture.draft_id}/refresh`,
      qualificationPath: `/api/v2/outreach/compositions/${fixture.composition_id}/qualification`});
    const page = await app.firstWindow();
    page.setDefaultTimeout(12_000);
    let pageErrors = 0;
    page.on('pageerror', () => { pageErrors++; });
    await page.emulateMedia({reducedMotion: 'reduce'});
    await page.getByRole('button', {name: 'Open Settings', exact: true}).click();
    await page.getByLabel('Service URL').fill(fixture.base_url);
    try { await page.getByLabel('Workspace key', {exact: true}).fill(fixture.workspace_key); }
    catch { throw Error('synthetic_credential_entry_failed'); }
    await page.getByRole('button', {name: 'Connect', exact: true}).click();
    await expect(page.getByText('Connection verified', {exact: true})).toBeVisible();

    const readComposition = () => page.evaluate(async id => {
      const result = await window.desktop.drafts.composition(id);
      if (!result.ok) throw Error('fixture_composition_read_failed');
      return result.data;
    }, fixture.composition_id);
    const before = await readComposition();
    expect(before.id).toBe(fixture.composition_id);
    expect(before.activity_id).toBe(fixture.activity_id);
    const targetIndex = before.drafts.findIndex(row => row.id === fixture.draft_id);
    const siblingIndex = before.drafts.findIndex(row => row.id === fixture.sibling_draft_id);
    expect(targetIndex).toBeGreaterThanOrEqual(0);
    expect(siblingIndex).toBeGreaterThanOrEqual(0);
    const original = before.drafts[targetIndex];
    expect(original.source_changed).toBe(false);
    const readCreator = () => page.evaluate(async id => {
      const result = await window.desktop.creators.detail(id);
      if (!result.ok) throw Error('fixture_creator_read_failed');
      return result.data;
    }, fixture.creator_id);
    const creatorBefore = await readCreator();
    const batch = await page.evaluate(async scope => {
      const result = await window.desktop.outreach.batch({activityId: scope.activityId, id: scope.batchId});
      if (!result.ok) throw Error('fixture_batch_read_failed');
      return result.data;
    }, {activityId: fixture.activity_id, batchId: before.recipient_batch_id});
    expect(batch.recipients.find(row => row.id === original.recipient_snapshot_id)?.snapshot.creator_id).toBe(fixture.creator_id);
    expect(before.send_ready).toBe(false);

    async function openDraft() {
      await page.getByRole('button', {name: 'Match', exact: true}).click();
      await page.getByRole('list', {name: 'Activities', exact: true})
        .locator(`button[data-activity-id="${fixture.activity_id}"]`).click();
      const history = await page.evaluate(async activityId => {
        const result = await window.desktop.drafts.compositions({activityId, offset: 0, limit: 50});
        if (!result.ok) throw Error('fixture_history_read_failed');
        return result.data.items.map(row => row.id);
      }, fixture.activity_id);
      const index = history.indexOf(fixture.composition_id);
      expect(index).toBeGreaterThanOrEqual(0);
      await page.getByText('History & saved lists', {exact: true}).click();
      await page.getByRole('button', {name: 'Draft history', exact: true}).click();
      await page.getByRole('button', {name: 'Open draft set', exact: true}).nth(index).click();
      await page.getByText('History & saved lists', {exact: true}).click();
      await expect(page.getByRole('region', {name: 'Draft email editor', exact: true})).toBeVisible();
      await page.getByRole('navigation', {name: 'Draft people'}).getByRole('button').nth(targetIndex).click();
    }
    await openDraft();
    const editor = page.getByRole('region', {name: 'Draft email editor', exact: true});
    const people = page.getByRole('navigation', {name: 'Draft people'}).getByRole('button');
    const labels = {firstName: 'Public name', channelName: 'Channel name', reference: 'Referenced work', observation: 'Observation'};
    const values = {firstName: 'Synthetic draft greeting', channelName: 'Synthetic draft channel',
      reference: 'Synthetic alternate reference', observation: 'Synthetic authored observation.'};
    expect(values.firstName).not.toBe(original.input.public_name);
    expect(values.channelName).not.toBe(original.input.channel_name);
    expect(values.reference).not.toBe(original.input.reference);
    await editor.getByRole('button', {name: 'Edit personalization', exact: true}).click();
    for (const key of Object.keys(labels) as Array<keyof typeof labels>) await editor.getByLabel(labels[key], {exact: true}).fill(values[key]);
    // Unsaved per-person sessions must survive a roster detour without HTTP writes.
    await people.nth(siblingIndex).click();
    await people.nth(targetIndex).click();
    for (const key of Object.keys(labels) as Array<keyof typeof labels>) await expect(editor.getByLabel(labels[key], {exact: true})).toHaveValue(values[key]);
    expect(await readComposition()).toEqual(before);
    const save = editor.getByRole('button', {name: 'Save changes', exact: true});
    await expect(save).toBeEnabled();
    await save.click();
    await expect(save).toBeDisabled();
    const full = (await readComposition()).drafts[targetIndex];
    expect(full.revision).toBe(original.revision + 1);
    expect(full.values).toEqual(values);
    expect(full.status).toBe('succeeded');
    expect(full.send_ready).toBe(false);
    expect(full.sender_facts_valid).toBe(false);
    expect(full.rendered).not.toBeNull();
    const preview = page.frameLocator('iframe[title="Saved email preview"]').locator('body');
    for (const value of Object.values(values)) await expect(preview).toContainText(value);
    const confirmations = page.locator('.sender-facts-editor');
    await confirmations.getByText('Sender confirmations', {exact: true}).click();
    await confirmations.getByRole('checkbox', {name: values.channelName, exact: true}).check();
    await expect(confirmations.locator('.sender-confirmation-context')).toContainText(values.reference);
    await expect(confirmations.locator('.sender-confirmation-context')).toContainText(values.observation);
    await expect(confirmations.getByRole('checkbox', {name: 'I follow these channels', exact: true})).not.toBeChecked();
    await page.screenshot({path: info.outputPath('confirm-current-draft-content.png')});
    await confirmations.getByRole('button', {name: 'Clear', exact: true}).click();
    await confirmations.getByText('Sender confirmations', {exact: true}).click();
    const qualify = () => page.evaluate(async compositionId => {
      const result = await window.desktop.sending.qualify({compositionId, data: {excluded: []}});
      if (!result.ok) throw Error('fixture_qualification_read_failed');
      return result.data;
    }, fixture.composition_id);
    const fullQualification = await qualify();
    expect(fullQualification.send_ready).toBe(false);
    expect(fullQualification.members.find(row => row.draft_id === fixture.draft_id)?.status).not.toBe('eligible');
    await page.screenshot({ path: info.outputPath('saved-override-preview.png') });

    await editor.getByRole('button', {name: 'Refresh sources', exact: true}).click();
    await editor.getByRole('button', {name: 'Refresh and keep overrides', exact: true}).click();
    await expect.poll(async () => (await readComposition()).drafts[targetIndex].revision).toBe(full.revision + 1);
    const refreshed = (await readComposition()).drafts[targetIndex];
    expect(refreshed.values).toEqual(values);
    expect(refreshed.status).toBe('succeeded');
    expect(refreshed.source_changed).toBe(false);
    expect(refreshed.sender_facts).toEqual({});
    await expect(editor.getByLabel('Public name', {exact: true})).toHaveValue(values.firstName);

    await editor.getByLabel('Observation', {exact: true}).fill('');
    await expect(save).toBeEnabled();
    await save.click();
    await expect(save).toBeDisabled();
    const partialComposition = await readComposition();
    const partial = partialComposition.drafts[targetIndex];
    expect(partial.revision).toBe(refreshed.revision + 1);
    expect(partial.values).toEqual({...values, observation: ''});
    expect(partial.status).toBe('needs_repair');
    expect(partial.send_ready).toBe(false);
    expect(partial.rendered).not.toBeNull();
    await expect(preview).toContainText(values.firstName);
    await expect(preview).not.toContainText(values.observation);
    await people.nth(siblingIndex).click();
    await people.nth(targetIndex).click();
    await expect(editor.getByLabel('Observation', {exact: true})).toHaveValue('');
    const partialQualification = await qualify();
    expect(partialQualification.send_ready).toBe(false);
    expect(partialQualification.members.find(row => row.draft_id === fixture.draft_id)?.status).not.toBe('eligible');
    expect(partialComposition.drafts.filter(row => row.id !== fixture.draft_id)).toEqual(before.drafts.filter(row => row.id !== fixture.draft_id));
    expect(await readCreator()).toEqual(creatorBefore);
    await page.reload();
    await page.waitForFunction(() => Boolean(window.desktop?.drafts));
    const after = await readComposition();
    expect(after).toEqual(partialComposition);
    await openDraft();
    await editor.getByRole('button', {name: 'Edit personalization', exact: true}).click();
    await expect(editor.getByLabel('Public name', {exact: true})).toHaveValue(values.firstName);
    await expect(editor.getByLabel('Referenced work', {exact: true})).toHaveValue(values.reference);
    await expect(editor.getByLabel('Observation', {exact: true})).toHaveValue('');
    await expect(preview).toContainText(values.reference);
    await page.screenshot({ path: info.outputPath('unfinished-draft-reopened.png') });
    expect(await readCreator()).toEqual(creatorBefore);
    const traffic = await app.evaluate(() => (globalThis as any).__personalizationTraffic) as Array<{method: string; path: string; allowed: boolean}>;
    expect(traffic.filter(row => row.method === 'PATCH')).toHaveLength(2);
    expect(traffic.filter(row => row.method === 'POST')).toHaveLength(3);
    expect(traffic.filter(row => row.method !== 'GET' && !row.allowed)).toEqual([]);
    expect(traffic.filter(row => row.allowed && row.path === `/api/v2/outreach/compositions/${fixture.composition_id}`).length).toBeGreaterThanOrEqual(2);
    expect(pageErrors).toBe(0);
    await writeFile(info.outputPath('verification.json'), JSON.stringify({
      scope: 'real-ipc-personalization', target, userData, realIPC: true, syntheticFixture: true,
      compositionId: fixture.composition_id, reload: true, pageErrors, traffic,
      draftOnly: true, unsavedRosterRetention: true, savedRosterRetention: true,
      refreshPreservesOverrides: true,
      completeDraftStatus: full.status, incompleteDraftStatus: partial.status,
      fullSendReady: fullQualification.send_ready, partialSendReady: partialQualification.send_ready,
    }, null, 2));
  } finally {
    await app?.close();
  }
});
