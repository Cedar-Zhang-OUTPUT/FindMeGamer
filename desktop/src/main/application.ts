import { app, BrowserWindow, dialog, ipcMain, Menu, protocol, safeStorage, session, shell } from 'electron';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { CredentialStore } from './credential-store';
import { WorkspaceGateway } from './gateway';
import { LibraryClient, LibraryClientError } from './library-client';
import { GameClient } from './game-client';
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
  handle('system:open-external', async value => {
    let url: string;
    try { url = externalUrl(value); } catch { throw new PublicFailure('invalid_link', 'Only valid HTTPS links can be opened.'); }
    await shell.openExternal(url);
  });
  window.on('closed', () => { for (const channel of channels) ipcMain.removeHandler(channel); rendererSession.protocol.unhandle('fmg'); });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: 'appMenu' }, { role: 'editMenu' },
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'togglefullscreen' }] }, { role: 'windowMenu' },
  ]));
  await window.loadURL(APP_URL);
  return { window, gateway, network };
}
