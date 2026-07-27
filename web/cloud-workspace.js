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
    <div class="ws-full-editor-note">
      <strong>Developer toolchain:</strong> Git and Git LFS · Python, pip and virtual environments · Node.js and npm · C/C++ build tools and CMake · ripgrep and fd · jq and SQLite · ShellCheck · editors, archive tools and process diagnostics.
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
  let runtimeAvailable = false;
  let currentRunning = false;

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

  function renderControls() {
    startButton.disabled = loading || !runtimeAvailable || currentRunning;
    connectButton.disabled = loading || !runtimeAvailable || !currentRunning;
    stopButton.disabled = loading || !runtimeAvailable || !currentRunning;
  }

  function showContainer(container) {
    currentRunning = Boolean(container?.running);
    if (!container) {
      renderControls();
      return;
    }
    boundaryNode.innerHTML = `<strong>Security boundary:</strong> developer user · ${container.cpu_limit || 2} CPU cores · ${container.memory_mb || 4096} MB RAM · ${container.pids_limit || 512} process limit · network ${container.network || 'none'}.`;
    state(
      `Workspace ${container.status || 'unknown'} · persistent repository attached`,
      currentRunning ? 'ready' : 'stopped',
    );
    renderControls();
  }

  async function refresh() {
    if (loading) return currentRunning;
    loading = true;
    renderControls();
    state('Checking the isolated workspace runtime…');
    try {
      const result = await request(`/api/v1/cloud-workspaces/repositories/${repositoryId}`);
      runtimeAvailable = Boolean(result.runtime?.configured && result.runtime?.ok);
      if (!result.runtime?.configured) {
        currentRunning = false;
        state(
          'Terminal deployment is incomplete. Configure the separate Docker workspace runtime and the control-plane runtime URL and token.',
          'not-configured',
        );
        return false;
      }
      if (!result.runtime?.ok) {
        currentRunning = false;
        state(result.runtime?.detail || 'Workspace runtime is unreachable.', 'error');
        return false;
      }
      if (result.container) {
        showContainer(result.container);
      } else {
        currentRunning = false;
        state('Workspace is ready to start. Files will remain on persistent storage.', 'stopped');
      }
      return currentRunning;
    } catch (error) {
      runtimeAvailable = false;
      currentRunning = false;
      state(error.message, 'error');
      return false;
    } finally {
      loading = false;
      renderControls();
    }
  }

  async function start() {
    if (loading || currentRunning || !runtimeAvailable) return;
    loading = true;
    renderControls();
    state('Starting an isolated workspace…');
    let started = false;
    try {
      const result = await request(
        `/api/v1/cloud-workspaces/repositories/${repositoryId}/start`,
        { method: 'POST' },
      );
      showContainer(result.container);
      started = currentRunning;
    } catch (error) {
      currentRunning = false;
      state(error.message, 'error');
    } finally {
      loading = false;
      renderControls();
    }
    if (started) await connect();
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
    terminal.writeln('Connecting a non-root developer shell in /workspace…\r\n');
    terminal.onData(data => {
      if (socket?.readyState === WebSocket.OPEN) socket.send(data);
    });
    return terminal;
  }

  async function connect() {
    if (!currentRunning || !runtimeAvailable) return;
    if (socket?.readyState === WebSocket.OPEN) {
      terminal?.focus();
      return;
    }
    connectButton.disabled = true;
    state('Creating a short-lived terminal ticket…');
    try {
      const [term, ticket] = await Promise.all([
        loadTerminal(),
        request(
          `/api/v1/cloud-workspaces/repositories/${repositoryId}/terminal-ticket`,
          { method: 'POST' },
        ),
      ]);
      socket = new WebSocket(ticket.websocket_url);
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        state('Terminal connected. Commands run as the non-root developer user.', 'ready');
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
        socket = null;
        state(event.reason || 'Terminal disconnected.', 'stopped');
        renderControls();
      };
    } catch (error) {
      state(error.message, 'error');
      renderControls();
    }
  }

  async function stop() {
    if (loading || !currentRunning) return;
    loading = true;
    renderControls();
    socket?.close(1000, 'Workspace stopped');
    state('Stopping workspace; persistent files will remain…');
    try {
      const result = await request(
        `/api/v1/cloud-workspaces/repositories/${repositoryId}/stop`,
        { method: 'POST' },
      );
      showContainer(result.container);
    } catch (error) {
      state(error.message, 'error');
    } finally {
      loading = false;
      renderControls();
    }
  }

  terminalTab.addEventListener('click', async () => {
    document.querySelectorAll('.ws-tab').forEach(tab => {
      tab.classList.toggle('active', tab === terminalTab);
    });
    document.querySelectorAll('.ws-panel').forEach(item => {
      item.classList.toggle('active', item === panel);
    });
    const running = await refresh();
    if (running) await connect();
  });
  startButton.addEventListener('click', start);
  connectButton.addEventListener('click', connect);
  stopButton.addEventListener('click', stop);
  renderControls();
})();
