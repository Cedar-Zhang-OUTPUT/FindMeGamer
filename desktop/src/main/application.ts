import { app, BrowserWindow, dialog, ipcMain, Menu, protocol, safeStorage, session, shell } from 'electron';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { CredentialStore } from './credential-store';
import { WorkspaceGateway } from './gateway';
import { LibraryClient, LibraryClientError } from './library-client';
import { GameClient } from './game-client';
import { CreatorClient } from './creator-client';
import { SettingsClient } from './settings-client';
import { MatchClient } from './match-client';
import { SavedSetClient } from './saved-set-client';
import { OutreachClient } from './outreach-client';
import { DraftsClient } from './drafts-client';
import { SendingClient } from './sending-client';
import { PreferencesStore } from './preferences-store';
import { UpdateChecker } from './update-checker';
import { APP_URL, CONTENT_POLICY, externalUrl, isTrustedFrame, resourcePath } from './policies';
import { PublicFailure, publicResult } from './transport';

export function registerApplicationScheme() {
  protocol.registerSchemesAsPrivileged([{ scheme: 'fmg', privileges: { standard: true, secure: true, supportFetchAPI: true } }]);
}

export async function createApplication(options: { show?: boolean; userDataDirectory?: string } = {}) {
  const rendererRoot = path.join(app.getAppPath(), 'out/renderer');
  const network = session.fromPartition('workspace-network');
  await network.setProxy({ mode: 'system' });
  const store = new CredentialStore(options.userDataDirectory ?? app.getPath('userData'), {
    isEncryptionAvailable: () => safeStorage.isAsyncEncryptionAvailable(),
    encryptString: plain => safeStorage.encryptStringAsync(plain),
    decryptString: async cipher => (await safeStorage.decryptStringAsync(cipher)).result,
  });
  const gateway = new WorkspaceGateway(store, (url, init) => network.fetch(url, init));
  const library = new LibraryClient((route, query) => gateway.request(route, query));
  const games = new GameClient(input => gateway.gameRequest(input));
  const creators = new CreatorClient(input => gateway.creatorRequest(input));
  const settings = new SettingsClient(input => gateway.settingsRequest(input));
  const match = new MatchClient(input => gateway.matchRequest(input));
  const savedSets = new SavedSetClient(input => gateway.savedSetRequest(input));
  const outreach = new OutreachClient(input => gateway.outreachRequest(input));
  const drafts = new DraftsClient(input => gateway.draftsRequest(input));
  const sending = new SendingClient(input => gateway.sendingRequest(input));
  const preferences = new PreferencesStore(options.userDataDirectory ?? app.getPath('userData'));
  // A separate ephemeral session follows the system proxy without workspace headers.
  const updateNetwork = session.fromPartition('updates-network');
  await updateNetwork.setProxy({mode:'system'});
  const updates = new UpdateChecker({installedVersion:app.getVersion(),fetcher:(url,init)=>updateNetwork.fetch(url as string,init),preferences});
  const rendererSession = session.fromPartition('renderer');
  rendererSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  rendererSession.setPermissionCheckHandler(() => false);
  await rendererSession.protocol.handle('fmg', async request => {
    const resource = resourcePath(request.url, rendererRoot);
    if (!resource || request.method !== 'GET') return new Response('Not found', { status: 404 });
    const contentTypes: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.svg': 'image/svg+xml', '.webp': 'image/webp', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.woff2': 'font/woff2' };
    try {
      return new Response(await readFile(resource), { headers: { 'Content-Type': contentTypes[path.extname(resource)] ?? 'application/octet-stream', 'Content-Security-Policy': CONTENT_POLICY, 'X-Content-Type-Options': 'nosniff', 'Cache-Control': 'no-store' } });
    } catch { return new Response('Not found', { status: 404 }); }
  });
  const window = new BrowserWindow({
    title: 'FindMeGamer', width: 1320, height: 920, minWidth: 720, minHeight: 560,
    show: options.show ?? true, backgroundColor: '#FFF9F1', titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload: path.join(app.getAppPath(), 'out/preload/index.cjs'), session: rendererSession,
      nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true,
      webviewTag: false, allowRunningInsecureContent: false, spellcheck: false,
    },
  });
  window.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.on('will-attach-webview', event => event.preventDefault());
  window.webContents.on('will-prevent-unload', event => {
    const choice = dialog.showMessageBoxSync(window, {
      type: 'question', buttons: ['Keep editing', 'Discard and leave'], defaultId: 0, cancelId: 0,
      message: 'Leave with unsaved changes?',
      detail: 'Unsaved edits and unresolved saves will be lost from this window. A submitted save may still complete on the server.',
      noLink: true,
    });
    // Electron interprets preventing this event as explicit permission to unload.
    if (choice === 1) event.preventDefault();
  });
  const channels: string[] = [];
  function handle(name: string, action: (input: any) => Promise<unknown>) {
    channels.push(name);
    ipcMain.handle(name, (event, input) => publicResult(async () => {
      if (event.sender !== window.webContents || !event.senderFrame || !isTrustedFrame(event.senderFrame.url, event.senderFrame === window.webContents.mainFrame)) {
        throw new PublicFailure('access_denied', 'This page cannot access the workspace.');
      }
      try { return await action(input); }
      catch (error) {
        if (error instanceof LibraryClientError) throw new PublicFailure(error.code, error.code === 'invalid_input' ? 'The Library request is invalid.' : 'The service returned an unsupported Library response. Retry or check the service version.', error.retryable);
        throw error;
      }
    }));
  }
  handle('connection:status', () => gateway.status());
  handle('connection:save', input => gateway.save(input));
  handle('connection:clear', () => gateway.clear());
  handle('connection:test', () => gateway.runCurrent(async () => {
    await library.session();
    const status = await gateway.status();
    const route = await network.resolveProxy(status.serviceUrl);
    return { authenticated: true, proxy: 'system', route: route === 'DIRECT' ? 'direct' : 'proxy' };
  }));
  handle('library:list', input => library.list(input));
  handle('library:detail', input => library.detail(input));
  handle('games:list', input => games.list(input));
  handle('games:detail', input => games.detail(input));
  handle('games:create', input => games.create(input));
  handle('games:update', input => games.update(input));
  handle('creators:list',input=>creators.list(input));
  handle('outreach:selections',input=>outreach.selections(input));
  handle('outreach:selection',input=>outreach.selection(input));
  handle('outreach:add',input=>outreach.add(input));
  handle('outreach:bulk',input=>outreach.bulk(input));
  handle('outreach:update',input=>outreach.update(input));
  handle('outreach:cancel',input=>outreach.cancel(input));
  handle('outreach:batches',input=>outreach.batches(input));
  handle('outreach:batch',input=>outreach.batch(input));
  handle('outreach:freeze',input=>outreach.freeze(input));
  handle('sending:qualify', input => sending.qualify(input));
  handle('sending:send', input => sending.send(input));
  handle('sending:batches', input => sending.batches(input));
  handle('sending:batch', input => sending.batch(input));
  handle('sending:retry', input => sending.retry(input));
  handle('sending:resolve', input => sending.resolve(input));
  handle('drafts:templates', input => drafts.templates(input));
  handle('drafts:template', input => drafts.template(input));
  handle('drafts:register-canonical', input => drafts.registerCanonical(input));
  handle('drafts:create-template', input => drafts.createTemplate(input));
  handle('drafts:compositions', input => drafts.compositions(input));
  handle('drafts:composition', input => drafts.composition(input));
  handle('drafts:create-composition', input => drafts.createComposition(input));
  handle('drafts:edit', input => drafts.edit(input));
  handle('drafts:refresh', input => drafts.refresh(input));
  handle('drafts:retry', input => drafts.retry(input));
  handle('drafts:sender-facts', input => drafts.senderFacts(input));
  handle('saved-sets:list',input=>savedSets.list(input));
  handle('saved-sets:detail',input=>savedSets.detail(input));
  handle('saved-sets:results',input=>savedSets.results(input));
  handle('saved-sets:create',input=>savedSets.create(input));
  handle('match:activities',input=>match.activities(input));
  handle('match:create-activity',input=>match.createActivity(input));
  handle('match:activity',input=>match.activity(input));
  handle('match:plans',input=>match.plans(input));
  handle('match:create-plan',input=>match.createPlan(input));
  handle('match:plan',input=>match.plan(input));
  handle('match:retry-plan',input=>match.retryPlan(input));
  handle('match:query',input=>match.query(input));
  handle('match:candidates',input=>match.candidates(input));
  handle('match:stop',input=>match.stop(input));
  handle('match:continue',input=>match.continueDiscovery(input));
  handle('match:evaluations',input=>match.evaluations(input));
  handle('match:evaluate',input=>match.evaluate(input));
  handle('match:evaluation',input=>match.evaluation(input));
  handle('match:evaluation-results',input=>match.evaluationResults(input));
  handle('match:retry-evaluation',input=>match.retryEvaluation(input));
  handle('creators:detail',input=>creators.detail(input));
  handle('creators:create',input=>creators.create(input));
  handle('creators:update',input=>creators.update(input));
  handle('creators:rebind',input=>creators.rebind(input));
  handle('creators:create-contact',input=>creators.createContact(input));
  handle('creators:update-contact',input=>creators.updateContact(input));
  handle('creators:works',input=>creators.works(input));
  handle('creators:create-work',input=>creators.createWork(input));
  handle('creators:update-work',input=>creators.updateWork(input));
  handle('settings:connection', input => settings.connection(input));
  handle('settings:collection', () => settings.collection());
  handle('settings:set-collection', input => settings.setCollection(input));
  handle('settings:replace-connection', input => settings.replaceConnection(input));
  handle('settings:test-connection', input => settings.testConnection(input));
  handle('settings:reanalysis', () => settings.reanalysis());
  handle('settings:save-reanalysis', input => settings.saveReanalysis(input));
  handle('settings:smtp', () => settings.smtp());
  handle('settings:save-smtp', input => settings.saveSMTP(input));
  handle('settings:test-smtp', () => settings.testSMTP());
  handle('settings:send-test-email', input => settings.sendTestEmail(input));
  handle('preferences:read', () => preferences.read());
  handle('preferences:update', input => preferences.update(input));
  handle('preferences:restore-appearance', () => preferences.restoreAppearance());
  handle('updates:status', () => updates.status());
  handle('updates:check', () => updates.check());
  handle('system:open-external', async value => {
    let url: string;
    try { url = externalUrl(value); } catch { throw new PublicFailure('invalid_link', 'Only valid HTTPS links can be opened.'); }
    await shell.openExternal(url);
  });
  const automaticCheck = () => {void updates.checkAutomatically().catch(()=>{});};
  app.on('activate',automaticCheck);
  window.on('closed', () => { app.removeListener('activate',automaticCheck);for (const channel of channels) ipcMain.removeHandler(channel); rendererSession.protocol.unhandle('fmg'); });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: 'appMenu' }, { role: 'editMenu' },
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'togglefullscreen' }] }, { role: 'windowMenu' },
  ]));
  await window.loadURL(APP_URL);
  automaticCheck();
  return { window, gateway, network };
}
