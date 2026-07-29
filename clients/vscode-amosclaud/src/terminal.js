'use strict';

const vscode = require('vscode');

const TOKEN_KEY = 'amosclaud.autonomousToken';
const TERMINAL_PROFILE_ID = 'amosclaud-autonomous.self-terminal';

function normalizeBaseUrl(value) {
  const candidate = String(value || 'https://www.amosclaud.com').trim().replace(/\/+$/, '');
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new Error('Amosclaud URL is invalid');
  }
  const secureRemote = parsed.protocol === 'https:' && Boolean(parsed.hostname);
  const localDevelopment =
    parsed.protocol === 'http:' &&
    ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
  if (!secureRemote && !localDevelopment) {
    throw new Error('Amosclaud URL must use HTTPS, except for exact localhost development hosts');
  }
  return candidate;
}

function configuration() {
  const config = vscode.workspace.getConfiguration('amosclaud');
  return {
    baseUrl: normalizeBaseUrl(config.get('baseUrl', 'https://www.amosclaud.com')),
    terminalProfile: config.get('terminalProfile', 'bash'),
  };
}

async function tokenOrConfigure(context) {
  let token = await context.secrets.get(TOKEN_KEY);
  if (!token) {
    await vscode.commands.executeCommand('amosclaud.configureToken');
    token = await context.secrets.get(TOKEN_KEY);
  }
  if (!token) throw new Error('A valid per-user Amosclaud Autonomous token is required');
  return token;
}

async function requestJson({ baseUrl, pathname, token, method = 'GET', payload }) {
  const headers = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (payload !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`${baseUrl}${pathname}`, {
    method,
    headers,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Amosclaud returned a non-JSON terminal response (${response.status})`);
  }
  if (!response.ok) {
    const detail = body.detail || body.error || text || `HTTP ${response.status}`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return body;
}

function terminalId() {
  const source =
    globalThis.crypto && typeof globalThis.crypto.randomUUID === 'function'
      ? globalThis.crypto.randomUUID().replaceAll('-', '')
      : `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
  return `term_${source.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 24)}`;
}

async function selectRepository(context) {
  const token = await tokenOrConfigure(context);
  const config = configuration();
  const response = await requestJson({
    baseUrl: config.baseUrl,
    pathname: '/api/v1/vscode-terminal/repositories',
    token,
  });
  const repositories = Array.isArray(response.repositories) ? response.repositories : [];
  if (!repositories.length) {
    throw new Error('This Amosclaud account does not own a repository available to the self terminal');
  }
  if (repositories.length === 1) return repositories[0];
  const picked = await vscode.window.showQuickPick(
    repositories.map((repository) => ({
      label: String(repository.name || `Repository ${repository.id}`),
      description: `#${repository.id} · ${repository.default_branch || 'main'}`,
      detail: String(repository.description || 'Amosclaud repository'),
      repository,
    })),
    {
      title: 'Select an Amosclaud repository for this terminal',
      placeHolder: 'Each terminal is isolated to the selected user and repository',
      ignoreFocusOut: true,
    },
  );
  return picked ? picked.repository : undefined;
}

async function decodeMessage(data) {
  if (typeof data === 'string') return data;
  if (data instanceof ArrayBuffer) return new TextDecoder().decode(data);
  if (globalThis.Blob && data instanceof globalThis.Blob) return data.text();
  if (ArrayBuffer.isView(data)) {
    return new TextDecoder().decode(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
  }
  return String(data || '');
}

class AmosclaudPseudoterminal {
  constructor(context, repository, profile) {
    this.context = context;
    this.repository = repository;
    this.profile = profile;
    this.socket = undefined;
    this.dimensions = { rows: 30, columns: 120 };
    this.closed = false;
    this.writeEmitter = new vscode.EventEmitter();
    this.closeEmitter = new vscode.EventEmitter();
    this.onDidWrite = this.writeEmitter.event;
    this.onDidClose = this.closeEmitter.event;
  }

  open(initialDimensions) {
    if (initialDimensions) this.dimensions = initialDimensions;
    this.writeEmitter.fire('\r\n\x1b[1;36mConnecting to Amosclaud self terminal...\x1b[0m\r\n');
    this.connect().catch((error) => {
      this.writeEmitter.fire(
        `\r\n\x1b[31mAmosclaud terminal error: ${error instanceof Error ? error.message : String(error)}\x1b[0m\r\n`,
      );
      this.finish(1);
    });
  }

  async connect() {
    const token = await tokenOrConfigure(this.context);
    const config = configuration();
    await requestJson({
      baseUrl: config.baseUrl,
      pathname: `/api/v1/vscode-terminal/repositories/${this.repository.id}/start`,
      token,
      method: 'POST',
    });
    const sessionId = terminalId();
    const ticket = await requestJson({
      baseUrl: config.baseUrl,
      pathname: `/api/v1/vscode-terminal/repositories/${this.repository.id}/ticket`,
      token,
      method: 'POST',
      payload: { terminal_id: sessionId, profile: this.profile },
    });
    if (typeof globalThis.WebSocket !== 'function') {
      throw new Error('This VS Code extension host does not provide WebSocket support');
    }
    this.socket = new globalThis.WebSocket(ticket.websocket_url);
    this.socket.binaryType = 'arraybuffer';
    this.socket.onopen = () => {
      this.resize(this.dimensions);
    };
    this.socket.onmessage = async (event) => {
      const text = await decodeMessage(event.data);
      if (text) this.writeEmitter.fire(text);
    };
    this.socket.onerror = () => {
      this.writeEmitter.fire('\r\n\x1b[31mThe Amosclaud terminal connection failed.\x1b[0m\r\n');
    };
    this.socket.onclose = (event) => {
      if (event.reason) {
        this.writeEmitter.fire(`\r\n\x1b[2m${event.reason}\x1b[0m\r\n`);
      }
      this.finish(event.code === 1000 ? 0 : 1);
    };
  }

  handleInput(data) {
    if (this.socket && this.socket.readyState === globalThis.WebSocket.OPEN) {
      this.socket.send(data);
    }
  }

  setDimensions(dimensions) {
    this.dimensions = dimensions;
    this.resize(dimensions);
  }

  resize(dimensions) {
    if (!this.socket || this.socket.readyState !== globalThis.WebSocket.OPEN) return;
    this.socket.send(
      JSON.stringify({
        type: 'resize',
        rows: Number(dimensions.rows || 30),
        cols: Number(dimensions.columns || 120),
      }),
    );
  }

  close() {
    if (this.socket && this.socket.readyState === globalThis.WebSocket.OPEN) {
      this.socket.send(JSON.stringify({ type: 'terminate' }));
      this.socket.close(1000, 'Terminal closed by the user');
    }
    this.finish(0);
  }

  finish(code) {
    if (this.closed) return;
    this.closed = true;
    this.closeEmitter.fire(code);
    this.writeEmitter.dispose();
    this.closeEmitter.dispose();
  }
}

async function terminalProfile(context) {
  const repository = await selectRepository(context);
  if (!repository) return undefined;
  const config = configuration();
  const profile = ['bash', 'sh', 'python'].includes(config.terminalProfile)
    ? config.terminalProfile
    : 'bash';
  return new vscode.TerminalProfile({
    name: `Amosclaud · ${repository.name}`,
    pty: new AmosclaudPseudoterminal(context, repository, profile),
    iconPath: new vscode.ThemeIcon('cloud'),
    color: new vscode.ThemeColor('terminal.ansiCyan'),
  });
}

function registerTerminal(context) {
  const provider = {
    provideTerminalProfile: () => terminalProfile(context),
  };
  context.subscriptions.push(
    vscode.window.registerTerminalProfileProvider(TERMINAL_PROFILE_ID, provider),
    vscode.commands.registerCommand('amosclaud.openTerminal', async () => {
      try {
        const profile = await terminalProfile(context);
        if (!profile) return;
        const terminal = vscode.window.createTerminal(profile.options);
        terminal.show(true);
      } catch (error) {
        vscode.window.showErrorMessage(
          `Amosclaud terminal: ${error instanceof Error ? error.message : String(error)}`,
        );
      }
    }),
  );
}

module.exports = {
  AmosclaudPseudoterminal,
  TERMINAL_PROFILE_ID,
  decodeMessage,
  registerTerminal,
  terminalId,
};
