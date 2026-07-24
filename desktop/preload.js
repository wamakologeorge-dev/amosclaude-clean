const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('amosclaudDesktop', {
  platform: process.platform,
  isDesktopApp: true,
});
