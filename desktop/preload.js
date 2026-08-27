const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('amosclaudDesktop', {
  platform: process.platform,
  isDesktopApp: true,
  openProviderSetup: () => ipcRenderer.invoke('desktop:open-provider-setup'),
  provider: {
    getConfig: () => ipcRenderer.invoke('provider:get'),
    saveConfig: (config) => ipcRenderer.invoke('provider:save', config),
    clearConfig: () => ipcRenderer.invoke('provider:clear'),
    testConnection: () => ipcRenderer.invoke('provider:test'),
    request: (request) => ipcRenderer.invoke('provider:request', request),
  },
});
