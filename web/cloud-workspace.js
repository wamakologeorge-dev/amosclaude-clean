(() => {
  const tabs = document.querySelector('.ws-tabs');
  const main = document.querySelector('.ws-main');
  if (!tabs || !main) return;

  const parts = location.pathname.split('/').filter(Boolean);
  const repositoryId = parts.length === 2 && parts[0] === 'workspace' ? parts[1] : '';
  if (!/^\d+$/.test(repositoryId)) return;

  const terminalTab = document.createElement('button');
  terminalTab.className = 'ws-tab';
  terminalTab.dataset.tab = 'terminal';
  terminalTab.type = 'button';
  terminalTab.textContent = 'Terminal';
  tabs.appendChild(terminalTab);

  const panel = document.createElement('section');
  panel.className = 'ws-panel';
  panel.dataset.panel = 'terminal';
  panel.innerHTML = `
    <div class="ws-section-head">
      <div>
        <h2>Cloud terminal</h2>
        <p>Non-root shell inside an isolated workspace container. The repository files and Git history remain on persistent storage.</p>
      </div>
      <div class="ws-tool-form">
        <button id="cloud-workspace-start" type="button">Start workspace</button>
        <button id="cloud-workspace-connect" type="button" disabled>Connect terminal</button>
        <button id="cloud-workspace-stop" type="button" disabled>Stop</button>
      </div>
    </div>
    <div id="cloud-workspace-boundaries" class="ws-full-editor-note">
      <strong>Security boundary:</strong> developer user · maximum 2 CPU cores · maximum 4 GB RAM · no internal platform network access.
    </div>
    <p id="cloud-workspace-state" class="ws-status" role="status" aria-live="polite">Open this tab to check the isolated runtime.</p>
    <div id="cloud-terminal" style="height:480px;min-height:320px;border:1px solid #30363d;border-radius:10px;background:#050a10;padding:8px;overflow:hidden"></div>`;
  main.appendChild(panel);

  const startButton = panel.querySelector('#cloud-workspace-start');
  const connectButton = panel.querySelector('#cloud-workspace-connect');
  const stopButton = panel.querySelector('#cloud-workspace-stop');
  const stateNode = panel.querySelector('#cloud-workspace-state');
  const terminalHost = panel.querySelector('#cloud-terminal');
  const boundaryNode = panel.querySelector('#cloud-workspace-boundaries');

  let terminal = null;
  let socket = null;
  let loading = false;

  function state(message, kind = '') {
    stateNode.textContent = message;
    stateNode.dataset.state = kind;
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = { detail: text };
    }
    if (!response.ok) {
      throw new Error(payload?.detail || `Request failed (${response.status})`);
    }
    return payload || {};
  }

  function setRunning(running) {
    startButton.disabled = loading || running;
    connectButton.disabled = loading || !running;
    stopButton.disabled = loading || !running;
  }

  function showContainer(container) {
    const running = Boolean(container?.running);
    setRunning(running);
    if (!container) return;
    boundaryNode.innerHTML = `<strong>Security boundary:</strong> developer user · ${container.cpu_limit || 2} CPU cores · ${container.memory_mb || 4096} MB RAM · ${container.pids_limit || 512} process limit · network ${container.network || 'none'}.`;
    state(`Workspace ${container.status || 'unknown'} · persistent repository ${container.persistent_path || ''}`, running ? 'ready' : 'stopped');
  }

  async function refresh() {
    if (loading) return;
    loading = true;
    setRunning(false);
    state('Checking the isolated workspace runtime…');
    try {
      const result = await request(`/api/v1/cloud-workspaces/repositories/${repositoryId}`);
      if (!result.runtime?.configured) {
        state('Workspace runtime is not configured on this deployment.', 'not-configured');
        return;
      }
      if (!result.runtime?.ok) {
        state(result.runtime?.detail || 'Workspace runtime is unreachable.', 'error');
        return;
      }
      if (result.container) {
        showContainer(result.container);
      } else {
        setRunning(false);
        state('Workspace is ready to start. Files will remain on persistent storage.', 'stopped');
      }
    } catch (error) {
      setRunning(false);
      state(error.message, 'error');
    } finally {
      loading = false;
    }
  }

  async function start() {
    if (loading) return;
    loading = true;
    setRunning(false);
    state('Starting an isolated workspace…');
    try {
      const result = await request(`/api/v1/cloud-workspaces/repositories/${repositoryId}/start`, { method: 'POST' });
      showContainer(result.container);
    } catch (error) {
      setRunning(false);
      state(error.message, 'error');
    } finally {
      loading = false;
    }
  }

  async function loadTerminal() {
    if (terminal) return terminal;
    if (!document.querySelector('link[data-amosclaud-xterm]')) {
      const stylesheet = document.createElement('link');
      stylesheet.rel = 'stylesheet';
      stylesheet.href = 'https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css';
      stylesheet.dataset.amosclaudXterm = 'true';
      document.head.appendChild(stylesheet);
    }
    const module = await import('https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/+esm');
    terminal = new module.Terminal({
      cursorBlink: true,
      convertEol: true,
      fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, monospace',
      fontSize: 14,
      scrollback: 5000,
      theme: { background: '#050a10', foreground: '#e6edf3' },
    });
    terminal.open(terminalHost);
    terminal.writeln('\x1b[1;36mAmosclaud isolated terminal\x1b[0m');
    terminal.writeln('Connect to begin a non-root shell in /workspace.\r\n');
    terminal.onData(data => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(data);
    });
    return terminal;
  }

  async function connect() {
    if (socket?.readyState === WebSocket.OPEN) {
      terminal?.focus();
      return;
    }
    connectButton.disabled = true;
    state('Creating a short-lived terminal ticket…');
    try {
      const [term, ticket] = await Promise.all([
        loadTerminal(),
        request(`/api/v1/cloud-workspaces/repositories/${repositoryId}/terminal-ticket`, { method: 'POST' }),
      ]);
      socket = new WebSocket(ticket.websocket_url);
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        state('Terminal connected. The ticket expires for new connections after two minutes.', 'ready');
        term.focus();
      };
      socket.onmessage = event => {
        if (typeof event.data === 'string') {
          term.write(event.data);
        } else {
          term.write(new Uint8Array(event.data));
        }
      };
      socket.onerror = () => state('Terminal connection failed.', 'error');
      socket.onclose = event => {
        state(event.reason || 'Terminal disconnected.', 'stopped');
        connectButton.disabled = false;
      };
    } catch (error) {
      connectButton.disabled = false;
      state(error.message, 'error');
    }
  }

  async function stop() {
    if (loading) return;
    loading = true;
    socket?.close(1000, 'Workspace stopped');
    state('Stopping workspace; persistent files will remain…');
    try {
      const result = await request(`/api/v1/cloud-workspaces/repositories/${repositoryId}/stop`, { method: 'POST' });
      showContainer(result.container);
    } catch (error) {
      state(error.message, 'error');
    } finally {
      loading = false;
    }
  }

  terminalTab.addEventListener('click', () => {
    document.querySelectorAll('.ws-tab').forEach(tab => tab.classList.toggle('active', tab === terminalTab));
    document.querySelectorAll('.ws-panel').forEach(item => item.classList.toggle('active', item === panel));
    refresh();
  });
  startButton.addEventListener('click', start);
  connectButton.addEventListener('click', connect);
  stopButton.addEventListener('click', stop);
})();
