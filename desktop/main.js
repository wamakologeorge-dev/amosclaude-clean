'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const {
  app,
  BrowserWindow,
  Menu,
  ipcMain,
  safeStorage,
  shell,
} = require('electron');
const { autoUpdater } = require('electron-updater');

const {
  DEFAULT_AMOSCLAUD_URL,
  DEFAULT_MODEL,
  SUPPORTED_GATEWAY_PATHS,
  gatewayUrl,
  normalizeApiKey,
  normalizeBaseUrl,
  normalizeProviderConfig,
  publicProviderConfig,
} = require('./provider-config');

const CONFIG_FILE = 'provider-config.json';
const CONFIG_VERSION = 1;
const GATEWAY_TIMEOUT_MS = 12000;
const MAX_GATEWAY_REQUEST_BYTES = 1_000_000;
const MAX_GATEWAY_RESPONSE_BYTES = 2_000_000;
const DEFAULT_APP_URL = safeUrl(process.env.AMOSCLAUD_URL, DEFAULT_AMOSCLAUD_URL);
const APP_ORIGIN = new URL(DEFAULT_APP_URL).origin;

let mainWindow;
let providerWindow;

function safeUrl(value, fallback) {
  try {
    return normalizeBaseUrl(value || fallback);
  } catch {
    return normalizeBaseUrl(fallback);
  }
}

function providerConfigPath() {
  return path.join(app.getPath('userData'), CONFIG_FILE);
}

function decryptStoredKey(value) {
  if (!value || !safeStorage.isEncryptionAvailable()) return '';
  return safeStorage.decryptString(Buffer.from(value, 'base64'));
}

function readStoredProviderConfig() {
  try {
    const raw = fs.readFileSync(providerConfigPath(), 'utf8');
    const saved = JSON.parse(raw);
    if (!saved || saved.version !== CONFIG_VERSION) return null;
    const apiKey = decryptStoredKey(saved.apiKey);
    return normalizeProviderConfig(
      {
        baseUrl: saved.baseUrl,
        model: saved.model,
        apiKey,
      },
      { allowMissingKey: true },
    );
  } catch {
    // A corrupt or unavailable OS-store entry should not prevent the Desktop
    // shell from opening. The setup window can replace it safely.
    return null;
  }
}

function resolvedProviderConfig() {
  const stored = readStoredProviderConfig();
  const hasEnvironmentSettings = Boolean(
    process.env.AMOSCLAUD_API_KEY ||
      process.env.AMOSCLAUD_GATEWAY_URL ||
      process.env.AMOSCLAUD_MODEL,
  );
  if (hasEnvironmentSettings || stored) {
    try {
      const config = normalizeProviderConfig(
        {
          baseUrl:
            process.env.AMOSCLAUD_GATEWAY_URL ||
            process.env.AMOSCLAUD_URL ||
            stored?.baseUrl ||
            DEFAULT_AMOSCLAUD_URL,
          model: process.env.AMOSCLAUD_MODEL || stored?.model || DEFAULT_MODEL,
          apiKey: process.env.AMOSCLAUD_API_KEY || stored?.apiKey || '',
        },
        { allowMissingKey: true },
      );
      return {
        config,
        source: process.env.AMOSCLAUD_API_KEY
          ? 'environment'
          : stored
            ? 'secure-storage'
            : 'environment',
      };
    } catch {
      // Fall through to safe defaults if an environment override is malformed.
    }
  }

  const defaults = normalizeProviderConfig(
    {
      baseUrl: DEFAULT_APP_URL,
      model: DEFAULT_MODEL,
      apiKey: '',
    },
    { allowMissingKey: true },
  );
  return { config: defaults, source: 'defaults' };
}

function publicProviderState() {
  const { config, source } = resolvedProviderConfig();
  return publicProviderConfig(config, source);
}

function writeStoredProviderConfig(config) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error(
      'OS secure storage is unavailable. Enable the system keychain, or use AMOSCLAUD_API_KEY for this session.',
    );
  }

  const filePath = providerConfigPath();
  const directory = path.dirname(filePath);
  fs.mkdirSync(directory, { recursive: true });
  const saved = {
    version: CONFIG_VERSION,
    baseUrl: config.baseUrl,
    model: config.model,
    apiKey: safeStorage.encryptString(config.apiKey).toString('base64'),
  };
  const temporaryPath = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(temporaryPath, JSON.stringify(saved), { encoding: 'utf8', mode: 0o600 });
  fs.renameSync(temporaryPath, filePath);
}

function saveProviderConfig(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error('Provider configuration must be an object');
  }
  const current = resolvedProviderConfig().config;
  const apiKey = normalizeApiKey(input.apiKey, { required: false }) || current.apiKey;
  const config = normalizeProviderConfig(
    {
      baseUrl: input.baseUrl || current.baseUrl,
      model: input.model || current.model,
      apiKey,
    },
    { allowMissingKey: false },
  );
  writeStoredProviderConfig(config);
  return publicProviderConfig(config, 'secure-storage');
}

function clearStoredProviderConfig() {
  try {
    fs.unlinkSync(providerConfigPath());
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
  return publicProviderState();
}

function gatewayError(status, body) {
  let detail = '';
  if (body && typeof body === 'object') {
    detail = body.detail || body.error || body.message || '';
    if (typeof detail !== 'string') detail = JSON.stringify(detail);
  }
  return new Error(
    `Amosclaud gateway rejected the request (${status}): ${detail || 'no error detail returned'}`,
  );
}

async function requestGateway(pathname, method = 'GET', body, overrideConfig) {
  if (!SUPPORTED_GATEWAY_PATHS.has(pathname)) {
    throw new Error('This Desktop gateway only permits supported Amosclaud API paths');
  }
  const expectedMethod = pathname === '/v1/models' ? 'GET' : 'POST';
  if (method !== expectedMethod) {
    throw new Error(`${pathname} only supports ${expectedMethod} requests`);
  }

  const config = overrideConfig || resolvedProviderConfig().config;
  const apiKey = normalizeApiKey(config.apiKey, { required: true });
  const encodedBody = body === undefined ? undefined : JSON.stringify(body);
  if (encodedBody && Buffer.byteLength(encodedBody, 'utf8') > MAX_GATEWAY_REQUEST_BYTES) {
    throw new Error('Amosclaud gateway request exceeded the Desktop safety limit');
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), GATEWAY_TIMEOUT_MS);
  try {
    const response = await fetch(gatewayUrl(config.baseUrl, pathname), {
      method,
      headers: {
        Accept: 'application/json',
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
        'User-Agent': 'amosclaud-desktop/1.0',
      },
      body: encodedBody,
      signal: controller.signal,
    });
    const text = await response.text();
    if (text.length > MAX_GATEWAY_RESPONSE_BYTES) {
      throw new Error('Amosclaud gateway response exceeded the Desktop safety limit');
    }
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      throw new Error(`Amosclaud gateway returned non-JSON data (${response.status})`);
    }
    if (!response.ok) throw gatewayError(response.status, payload);
    return { status: response.status, payload };
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error('Amosclaud gateway did not respond within 12 seconds');
    }
    if (error instanceof TypeError) {
      throw new Error('Could not reach the Amosclaud gateway. Check the provider URL and network.');
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function testProviderConnection(input) {
  let config = resolvedProviderConfig().config;
  if (input && typeof input === 'object' && !Array.isArray(input)) {
    const typedKey = normalizeApiKey(input.apiKey, { required: false }) || config.apiKey;
    config = normalizeProviderConfig(
      {
        baseUrl: input.baseUrl || config.baseUrl,
        model: input.model || config.model,
        apiKey: typedKey,
      },
      { allowMissingKey: false },
    );
  }
  const result = await requestGateway('/v1/models', 'GET', undefined, config);
  const models = Array.isArray(result.payload.data)
    ? result.payload.data
        .filter((model) => model && typeof model.id === 'string')
        .map((model) => model.id)
        .slice(0, 100)
    : [];
  return {
    ok: true,
    status: result.status,
    baseUrl: config.baseUrl,
    apiBaseUrl: config.apiBaseUrl,
    model: config.model,
    models,
  };
}

async function providerRequest(input) {
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    throw new Error('Gateway request must be an object');
  }
  const pathname = String(input.path || '');
  const method = String(input.method || (pathname === '/v1/models' ? 'GET' : 'POST')).toUpperCase();
  const result = await requestGateway(pathname, method, input.body);
  return { status: result.status, body: result.payload };
}

function isTrustedSender(event) {
  if (providerWindow && event.sender === providerWindow.webContents) return true;
  try {
    return new URL(event.senderFrame?.url || '').origin === APP_ORIGIN;
  } catch {
    return false;
  }
}

function requireTrustedSender(event) {
  if (!isTrustedSender(event)) throw new Error('Untrusted Desktop IPC sender');
}

function openExternal(url) {
  try {
    const parsed = new URL(url);
    if (parsed.protocol === 'https:' || parsed.protocol === 'http:') shell.openExternal(url);
  } catch {
    // Ignore malformed or non-web targets.
  }
}

function isAllowedNavigation(url, allowedOrigin, allowedFilePath) {
  const target = new URL(url);
  if (allowedFilePath) {
    return target.protocol === 'file:' && target.href === pathToFileURL(allowedFilePath).href;
  }
  return target.origin === allowedOrigin;
}

function configureWindowNavigation(win, allowedOrigin, allowedFilePath) {
  win.webContents.setWindowOpenHandler(({ url }) => {
    try {
      if (isAllowedNavigation(url, allowedOrigin, allowedFilePath)) return { action: 'allow' };
    } catch {
      // Fall through to the safe external-handler path.
    }
    openExternal(url);
    return { action: 'deny' };
  });

  win.webContents.on('will-navigate', (event, url) => {
    try {
      if (isAllowedNavigation(url, allowedOrigin, allowedFilePath)) return;
    } catch {
      // Treat malformed URLs as external and block them.
    }
    event.preventDefault();
    openExternal(url);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 920,
    minWidth: 900,
    minHeight: 640,
    title: 'Amosclaud',
    backgroundColor: '#111827',
    autoHideMenuBar: false,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });

  configureWindowNavigation(mainWindow, APP_ORIGIN);
  mainWindow.on('closed', () => {
    mainWindow = undefined;
  });
  mainWindow.loadURL(DEFAULT_APP_URL);
}

function openProviderSetupWindow() {
  if (providerWindow && !providerWindow.isDestroyed()) {
    providerWindow.focus();
    return;
  }

  providerWindow = new BrowserWindow({
    width: 580,
    height: 720,
    minWidth: 500,
    minHeight: 620,
    title: 'Amosclaud Gateway Provider Setup',
    parent: mainWindow,
    modal: false,
    backgroundColor: '#101827',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
    },
  });
  const providerPagePath = path.join(__dirname, 'provider.html');
  configureWindowNavigation(providerWindow, null, providerPagePath);
  providerWindow.on('closed', () => {
    providerWindow = undefined;
  });
  providerWindow.loadFile(providerPagePath);
}

function createApplicationMenu() {
  const template = [
    {
      label: 'Amosclaud',
      submenu: [
        {
          label: 'Gateway provider setup',
          accelerator: process.platform === 'darwin' ? 'Cmd+,' : 'Ctrl+,',
          click: openProviderSetupWindow,
        },
        { type: 'separator' },
        { role: 'quit' },
      ],
    },
    {
      role: 'viewMenu',
    },
  ];
  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

ipcMain.handle('provider:get', (event) => {
  requireTrustedSender(event);
  return publicProviderState();
});

ipcMain.handle('provider:save', (event, input) => {
  requireTrustedSender(event);
  return saveProviderConfig(input);
});

ipcMain.handle('provider:clear', (event) => {
  requireTrustedSender(event);
  return clearStoredProviderConfig();
});

ipcMain.handle('provider:test', (event, input) => {
  requireTrustedSender(event);
  return testProviderConnection(input);
});

ipcMain.handle('provider:request', (event, input) => {
  requireTrustedSender(event);
  return providerRequest(input);
});

ipcMain.handle('desktop:open-provider-setup', (event) => {
  requireTrustedSender(event);
  openProviderSetupWindow();
  return { opened: true };
});

app.whenReady().then(() => {
  createApplicationMenu();
  createWindow();
  if (process.argv.includes('--configure') || process.env.AMOSCLAUD_DESKTOP_CONFIGURE === '1') {
    openProviderSetupWindow();
  }
  autoUpdater.checkForUpdatesAndNotify().catch(() => {});

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
