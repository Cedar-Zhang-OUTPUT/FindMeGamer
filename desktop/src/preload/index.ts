import { contextBridge, ipcRenderer } from 'electron';
import type { DesktopBridge } from '../shared/bridge';

const bridge: DesktopBridge = {
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
  openExternal: url => ipcRenderer.invoke('system:open-external', url),
};
contextBridge.exposeInMainWorld('desktop', bridge);
