import { app, BrowserWindow, dialog } from 'electron';
import path from 'node:path';
import { createApplication, registerApplicationScheme } from './application';

app.setName('FindMeGamer');
const userDataOverride = app.commandLine.getSwitchValue('user-data-dir');
app.setPath('userData', userDataOverride ? path.resolve(userDataOverride) : path.join(app.getPath('appData'), 'FindMeGamerDesktop'));
registerApplicationScheme();
const locked = app.requestSingleInstanceLock();
if (!locked) app.quit();
else {
  app.on('second-instance', () => { const window = BrowserWindow.getAllWindows()[0]; window?.show(); window?.focus(); });
  app.whenReady().then(() => createApplication()).catch(() => {
    dialog.showErrorBox('FindMeGamer could not start', 'The desktop resources could not be loaded. Rebuild or reinstall this version.');
    app.quit();
  });
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) void createApplication(); });
  app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
}
