const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const { autoUpdater } = require('electron-updater');

const AMOSCLAUD_URL = process.env.AMOSCLAUD_URL || 'https://amosclaud.com';

function createWindow() {
  const win = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 900,
    minHeight: 640,
    title: 'Amosclaud',
    backgroundColor: '#111827',
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  win.webContents.setWindowOpenHandler(({ url }) => {
    const target = new URL(url);
    const appOrigin = new URL(AMOSCLAUD_URL).origin;
    if (target.origin === appOrigin) return { action: 'allow' };
    shell.openExternal(url);
    return { action: 'deny' };
  });

  win.webContents.on('will-navigate', (event, url) => {
    const target = new URL(url);
    const appOrigin = new URL(AMOSCLAUD_URL).origin;
    if (target.origin !== appOrigin) {
      event.preventDefault();
      shell.openExternal(url);
    }
  });

  win.loadURL(AMOSCLAUD_URL);
}

app.whenReady().then(() => {
  createWindow();
  autoUpdater.checkForUpdatesAndNotify().catch(() => {});

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
