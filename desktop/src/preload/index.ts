import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopBridge } from '../shared/bridge';

const bridge: DesktopBridge = {
  creators: {
    list: input => ipcRenderer.invoke('creators:list',input),
    detail: id => ipcRenderer.invoke('creators:detail',id),
    create: input => ipcRenderer.invoke('creators:create',input),
    update: input => ipcRenderer.invoke('creators:update',input),
    rebind: input => ipcRenderer.invoke('creators:rebind',input),
    createContact: input => ipcRenderer.invoke('creators:create-contact',input),
    updateContact: input => ipcRenderer.invoke('creators:update-contact',input),
    works: input => ipcRenderer.invoke('creators:works',input),
    createWork: input => ipcRenderer.invoke('creators:create-work',input),
    updateWork: input => ipcRenderer.invoke('creators:update-work',input),
  },
  settings: {
    connection: service => ipcRenderer.invoke('settings:connection', service),
    replaceConnection: input => ipcRenderer.invoke('settings:replace-connection', input),
    testConnection: service => ipcRenderer.invoke('settings:test-connection', service),
    reanalysis: () => ipcRenderer.invoke('settings:reanalysis'),
    saveReanalysis: input => ipcRenderer.invoke('settings:save-reanalysis', input),
    smtp: () => ipcRenderer.invoke('settings:smtp'),
    saveSMTP: input => ipcRenderer.invoke('settings:save-smtp', input),
    testSMTP: () => ipcRenderer.invoke('settings:test-smtp'),
    sendTestEmail: input => ipcRenderer.invoke('settings:send-test-email', input),
  },
  preferences: {
    read: () => ipcRenderer.invoke('preferences:read'),
    update: input => ipcRenderer.invoke('preferences:update', input),
    restoreAppearance: () => ipcRenderer.invoke('preferences:restore-appearance'),
  },
  updates: {
    status: () => ipcRenderer.invoke('updates:status'),
    check: () => ipcRenderer.invoke('updates:check'),
  },
  connection: {
    status: () => ipcRenderer.invoke('connection:status'),
    save: input => ipcRenderer.invoke('connection:save', input),
    test: () => ipcRenderer.invoke('connection:test'),
    clear: () => ipcRenderer.invoke('connection:clear'),
  },
  library: {
    list: input => ipcRenderer.invoke('library:list', input),
    detail: input => ipcRenderer.invoke('library:detail', input),
  },
  games: {
    list: input => ipcRenderer.invoke('games:list', input),
    detail: id => ipcRenderer.invoke('games:detail', id),
    create: input => ipcRenderer.invoke('games:create', input),
    update: input => ipcRenderer.invoke('games:update', input),
  },
  openExternal: url => ipcRenderer.invoke('system:open-external', url),
};
contextBridge.exposeInMainWorld('desktop', bridge);
