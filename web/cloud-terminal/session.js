import { apiRequest, terminalApi } from './api.js';

let terminalModules = null;

async function loadTerminalModules() {
  if (terminalModules) return terminalModules;
  terminalModules = Promise.all([
    import('https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/+esm'),
    import('https://cdn.jsdelivr.net/npm/@xterm/addon-fit@0.10.0/+esm'),
    import('https://cdn.jsdelivr.net/npm/@xterm/addon-search@0.15.0/+esm'),
    import('https://cdn.jsdelivr.net/npm/@xterm/addon-web-links@0.11.0/+esm'),
  ]).then(([core, fit, search, links]) => ({
    Terminal: core.Terminal,
    FitAddon: fit.FitAddon,
    SearchAddon: search.SearchAddon,
    WebLinksAddon: links.WebLinksAddon,
  }));
  return terminalModules;
}

function safeFilename(value) {
  return String(value || 'terminal')
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'terminal';
}

export class CloudTerminalSession {
  constructor({ repositoryId, id, profile, title, onState, onFocus }) {
    this.repositoryId = repositoryId;
    this.id = id;
    this.profile = profile;
    this.title = title;
    this.onState = onState;
    this.onFocus = onFocus;
    this.state = 'disconnected';
    this.socket = null;
    this.terminal = null;
    this.fitAddon = null;
    this.searchAddon = null;
    this.host = null;
    this.resizeObserver = null;
    this.disposables = [];
    this.connectAttempt = 0;
    this.connectPromise = null;
  }

  setState(state, detail = '') {
    this.state = state;
    this.onState?.(this, state, detail);
  }

  isConnected() {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  async mount(host) {
    if (this.terminal) return;
    this.host = host;
    const { Terminal, FitAddon, SearchAddon, WebLinksAddon } = await loadTerminalModules();
    this.terminal = new Terminal({
      cursorBlink: true,
      cursorStyle: 'bar',
      convertEol: true,
      allowProposedApi: false,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 13,
      lineHeight: 1.16,
      scrollback: 10000,
      theme: {
        background: '#050a10',
        foreground: '#e6edf3',
        cursor: '#58a6ff',
        selectionBackground: '#1f6feb66',
        black: '#484f58',
        red: '#ff7b72',
        green: '#3fb950',
        yellow: '#d29922',
        blue: '#58a6ff',
        magenta: '#bc8cff',
        cyan: '#39c5cf',
        white: '#b1bac4',
        brightBlack: '#6e7681',
        brightRed: '#ffa198',
        brightGreen: '#56d364',
        brightYellow: '#e3b341',
        brightBlue: '#79c0ff',
        brightMagenta: '#d2a8ff',
        brightCyan: '#56d4dd',
        brightWhite: '#f0f6fc',
      },
    });
    this.fitAddon = new FitAddon();
    this.searchAddon = new SearchAddon();
    this.terminal.loadAddon(this.fitAddon);
    this.terminal.loadAddon(this.searchAddon);
    this.terminal.loadAddon(new WebLinksAddon());
    this.terminal.open(host);
    this.terminal.writeln('\x1b[1;36mAmosclaud cloud terminal\x1b[0m');
    this.terminal.writeln(`Persistent ${this.profile} session · ${this.id}\r\n`);

    this.disposables.push(
      this.terminal.onData(data => {
        if (this.isConnected()) this.socket.send(data);
      }),
      this.terminal.onFocus(() => this.onFocus?.(this)),
      this.terminal.onResize(size => this.sendControl({ type: 'resize', ...size })),
    );

    this.resizeObserver = new ResizeObserver(() => this.fit());
    this.resizeObserver.observe(host);
    queueMicrotask(() => this.fit());
  }

  async connect() {
    if (!this.terminal) throw new Error('Terminal session is not mounted.');
    if (this.isConnected()) {
      this.focus();
      return;
    }
    if (this.connectPromise) return this.connectPromise;

    const attempt = ++this.connectAttempt;
    this.setState('connecting', 'Requesting a signed cloud terminal ticket…');
    this.connectPromise = (async () => {
      const ticket = await apiRequest(terminalApi(this.repositoryId, '/terminal-ticket-v2'), {
        method: 'POST',
        body: JSON.stringify({ terminal_id: this.id, profile: this.profile }),
      });
      if (attempt !== this.connectAttempt) return;

      await new Promise((resolve, reject) => {
        const socket = new WebSocket(ticket.websocket_url);
        this.socket = socket;
        socket.binaryType = 'arraybuffer';
        let opened = false;

        socket.onopen = () => {
          if (socket !== this.socket) return;
          opened = true;
          this.setState('connected', 'Connected to the Amosclaud cloud runtime.');
          this.fit();
          this.sendControl({
            type: 'resize',
            cols: this.terminal.cols,
            rows: this.terminal.rows,
          });
          this.focus();
          resolve();
        };
        socket.onmessage = event => {
          if (typeof event.data === 'string') this.terminal.write(event.data);
          else this.terminal.write(new Uint8Array(event.data));
        };
        socket.onerror = () => {
          if (socket !== this.socket) return;
          this.setState('error', 'Cloud terminal connection failed.');
          if (!opened) reject(new Error('Cloud terminal connection failed.'));
        };
        socket.onclose = event => {
          if (socket !== this.socket) return;
          this.socket = null;
          const detail = event.reason || (event.wasClean ? 'Terminal disconnected.' : 'Cloud connection closed unexpectedly.');
          this.setState(event.wasClean ? 'disconnected' : 'error', detail);
          if (!opened) reject(new Error(detail));
        };
      });
    })();

    try {
      await this.connectPromise;
    } catch (error) {
      this.setState('error', error.message);
      throw error;
    } finally {
      this.connectPromise = null;
    }
  }

  sendControl(payload) {
    if (!this.isConnected()) return;
    this.socket.send(JSON.stringify(payload));
  }

  async runCommand(command) {
    const prepared = String(command || '').replace(/\x00/g, '').trim();
    if (!prepared) return false;
    await this.connect();
    if (!this.isConnected()) throw new Error('Terminal is not connected.');
    this.socket.send(`${prepared}\r`);
    this.focus();
    return true;
  }

  fit() {
    if (!this.fitAddon || !this.host?.isConnected) return;
    try {
      this.fitAddon.fit();
    } catch (_error) {
      // A hidden tab can have no measurable size. It will fit after activation.
    }
  }

  focus() {
    this.terminal?.focus();
    this.onFocus?.(this);
  }

  disconnect(reason = 'Terminal disconnected') {
    this.connectAttempt += 1;
    this.connectPromise = null;
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      try {
        socket.close(1000, reason);
      } catch (_error) {
        // The socket may already be closed.
      }
    }
    this.setState('disconnected', reason);
  }

  terminate() {
    this.sendControl({ type: 'terminate' });
    this.disconnect('Terminal session ended');
  }

  clear() {
    this.terminal?.clear();
  }

  findNext(term) {
    return this.searchAddon?.findNext(term, {
      caseSensitive: false,
      incremental: true,
      decorations: {
        matchBackground: '#d2992266',
        activeMatchBackground: '#a371f7aa',
      },
    }) || false;
  }

  findPrevious(term) {
    return this.searchAddon?.findPrevious(term, {
      caseSensitive: false,
      decorations: {
        matchBackground: '#d2992266',
        activeMatchBackground: '#a371f7aa',
      },
    }) || false;
  }

  outputText(maxCharacters = 12000) {
    if (!this.terminal) return '';
    const buffer = this.terminal.buffer.active;
    const lines = [];
    for (let index = 0; index < buffer.length; index += 1) {
      const line = buffer.getLine(index);
      if (line) lines.push(line.translateToString(true));
    }
    return lines.join('\n').trimEnd().slice(-maxCharacters);
  }

  async copy() {
    const text = this.terminal?.getSelection() || this.outputText();
    if (!text) return false;
    await navigator.clipboard.writeText(text);
    return true;
  }

  exportTranscript() {
    const transcript = this.outputText(500000);
    const blob = new Blob([transcript], { type: 'text/plain;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${safeFilename(this.title)}-${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(link.href), 1000);
  }

  dispose({ terminate = false } = {}) {
    if (terminate) this.terminate();
    else this.disconnect('Terminal tab closed');
    this.resizeObserver?.disconnect();
    this.disposables.forEach(item => item.dispose?.());
    this.disposables = [];
    this.terminal?.dispose();
    this.terminal = null;
    this.host = null;
  }
}
