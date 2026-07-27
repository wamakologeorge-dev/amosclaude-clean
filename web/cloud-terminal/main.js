import { apiRequest, repositoryIdFromLocation, terminalApi } from './api.js';
import { TerminalAgentHub } from './agent-hub.js';
import { CloudTerminalSession } from './session.js';

const repositoryId = repositoryIdFromLocation();
const tabs = document.querySelector('.ws-tabs');
const main = document.querySelector('.ws-main');
if (!repositoryId || !tabs || !main) throw new Error('Repository workspace required.');

function addStyle(href, marker) {
  if (document.querySelector(`link[${marker}]`)) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = href;
  link.setAttribute(marker, 'true');
  document.head.appendChild(link);
}

addStyle('/static/cloud-workspace.css', 'data-amosclaud-terminal-style');
addStyle('https://cdn.jsdelivr.net/npm/@xterm/xterm@5.5.0/css/xterm.css', 'data-amosclaud-xterm-style');

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
      <h2>Amosclaud cloud terminal</h2>
      <p>Persistent isolated terminals with Doctor, Fixer, Autonomous, and Underground support beside the command line.</p>
    </div>
    <div class="ws-tool-form">
      <button data-start type="button">Start workspace</button>
      <button data-stop type="button" disabled>Stop workspace</button>
    </div>
  </div>
  <div data-boundary class="ws-full-editor-note"><strong>Security boundary:</strong> non-root developer · 2 CPU · 4 GB RAM · 512 processes · isolated network.</div>
  <div class="ws-full-editor-note"><strong>Developer toolchain:</strong> Git, Git LFS, Python, Node.js, npm, C/C++, CMake, tmux, ripgrep, fd, jq, SQLite, ShellCheck, editors, archives, and diagnostics.</div>
  <p data-state class="ws-status" role="status" aria-live="polite">Open this tab to connect to the Amosclaud cloud runtime.</p>
  <div class="cloud-terminal-shell">
    <div class="cloud-terminal-toolbar">
      <label class="cloud-terminal-profile">New terminal profile
        <select data-profile><option value="bash">Bash</option><option value="sh">POSIX shell</option><option value="python">Python REPL</option></select>
      </label>
      <button data-new type="button" disabled>+ New terminal</button>
      <button data-split type="button" disabled>Split</button>
      <button data-reconnect type="button" disabled>Reconnect</button>
      <button data-search-toggle type="button" disabled>Search</button>
      <button data-copy type="button" disabled>Copy</button>
      <button data-export type="button" disabled>Export</button>
      <button data-clear type="button" disabled>Clear</button>
      <span data-cloud class="cloud-terminal-cloud-state">Cloud disconnected</span>
    </div>
    <div class="cloud-terminal-tabs" data-tabs></div>
    <div class="cloud-terminal-search" data-search hidden>
      <input data-search-input type="search" placeholder="Search terminal output" />
      <button data-search-prev type="button">Previous</button>
      <button data-search-next type="button">Next</button>
      <button data-search-close type="button">Close</button>
    </div>
    <div class="cloud-terminal-workbench">
      <div class="cloud-terminal-grid" data-grid><div class="cloud-terminal-empty" data-empty>Create a terminal session to begin.</div></div>
      <aside class="terminal-agent-hub" data-agent-hub></aside>
    </div>
    <p class="cloud-terminal-shortcuts"><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>\`</kbd> new terminal · <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> search · <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd> copy</p>
  </div>`;
main.appendChild(panel);

const q = selector => panel.querySelector(selector);
const ui = {
  start: q('[data-start]'), stop: q('[data-stop]'), boundary: q('[data-boundary]'), state: q('[data-state]'),
  profile: q('[data-profile]'), newTerminal: q('[data-new]'), split: q('[data-split]'), reconnect: q('[data-reconnect]'),
  searchToggle: q('[data-search-toggle]'), copy: q('[data-copy]'), export: q('[data-export]'), clear: q('[data-clear]'),
  cloud: q('[data-cloud]'), tabs: q('[data-tabs]'), search: q('[data-search]'), searchInput: q('[data-search-input]'),
  searchPrev: q('[data-search-prev]'), searchNext: q('[data-search-next]'), searchClose: q('[data-search-close]'),
  grid: q('[data-grid]'), empty: q('[data-empty]'), agentHub: q('[data-agent-hub]'),
};

const sessions = new Map();
let loading = false;
let runtimeAvailable = false;
let workspaceRunning = false;
let activeId = '';
let splitId = '';
let counter = 0;

function makeId() {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `term_${Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')}`;
}
function active() { return sessions.get(activeId) || null; }
function visible(id) { return id === activeId || id === splitId; }
function setState(message, kind = '') { ui.state.textContent = message; ui.state.dataset.state = kind; }
function setCloud(message, kind = '') { ui.cloud.textContent = message; ui.cloud.className = `cloud-terminal-cloud-state${kind ? ` ${kind}` : ''}`; }

function controls() {
  const has = Boolean(active());
  ui.start.disabled = loading || !runtimeAvailable || workspaceRunning;
  ui.stop.disabled = loading || !runtimeAvailable || !workspaceRunning;
  ui.newTerminal.disabled = loading || !workspaceRunning || sessions.size >= 8;
  ui.split.disabled = loading || !workspaceRunning || !has || sessions.size >= 8;
  ui.reconnect.disabled = loading || !workspaceRunning || !has;
  for (const button of [ui.searchToggle, ui.copy, ui.export, ui.clear]) button.disabled = !has;
}

function renderTabs() {
  ui.tabs.innerHTML = '';
  sessions.forEach(session => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `cloud-terminal-tab${session.id === activeId ? ' active' : ''}${session.id === splitId ? ' split' : ''}`;
    const dot = document.createElement('span'); dot.className = `cloud-terminal-tab-state ${session.state}`;
    const label = document.createElement('span'); label.className = 'cloud-terminal-tab-label'; label.textContent = session.title;
    const close = document.createElement('span'); close.className = 'cloud-terminal-tab-close'; close.textContent = '×';
    close.addEventListener('click', event => { event.stopPropagation(); closeSession(session.id); });
    button.append(dot, label, close);
    button.addEventListener('click', () => activateSession(session.id));
    ui.tabs.appendChild(button);
  });
}

function renderPanes() {
  ui.grid.querySelectorAll('.cloud-terminal-pane').forEach(pane => pane.hidden = !visible(pane.dataset.terminalId));
  ui.empty.hidden = sessions.size > 0;
  ui.grid.classList.toggle('is-split', Boolean(splitId && sessions.has(splitId)));
  ui.grid.querySelectorAll('.cloud-terminal-pane').forEach(pane => pane.classList.toggle('active', pane.dataset.terminalId === activeId));
  active()?.fit();
  sessions.get(splitId)?.fit();
}

function onSessionState(session, state, detail) {
  renderTabs();
  const connected = [...sessions.values()].filter(item => item.state === 'connected').length;
  setCloud(connected ? `Cloud connected · ${connected} terminal${connected === 1 ? '' : 's'}` : 'Cloud disconnected', connected ? 'connected' : state === 'error' ? 'error' : '');
  if (session.id === activeId && detail) setState(detail, state === 'connected' ? 'ready' : state === 'error' ? 'error' : '');
}

async function createSession({ profile = ui.profile.value, split = false } = {}) {
  if (!workspaceRunning || sessions.size >= 8) return null;
  const id = makeId();
  counter += 1;
  const session = new CloudTerminalSession({ repositoryId, id, profile, title: `${profile} ${counter}`, onState: onSessionState, onFocus: item => activateSession(item.id, false) });
  sessions.set(id, session);
  const pane = document.createElement('div'); pane.className = 'cloud-terminal-pane'; pane.dataset.terminalId = id; ui.grid.appendChild(pane);
  await session.mount(pane);
  if (split && activeId) splitId = id;
  activeId = id;
  renderTabs(); renderPanes(); controls();
  await session.connect().catch(() => undefined);
  return session;
}

function activateSession(id, focus = true) {
  if (!sessions.has(id)) return;
  activeId = id;
  if (splitId === activeId) splitId = '';
  renderTabs(); renderPanes(); controls();
  if (focus) active()?.focus();
}

function closeSession(id) {
  const session = sessions.get(id);
  if (!session) return;
  session.dispose({ terminate: true });
  sessions.delete(id);
  ui.grid.querySelector(`[data-terminal-id="${id}"]`)?.remove();
  if (splitId === id) splitId = '';
  if (activeId === id) activeId = sessions.keys().next().value || '';
  renderTabs(); renderPanes(); controls();
}

function stopAllSessions() {
  sessions.forEach(session => session.dispose());
  sessions.clear(); activeId = ''; splitId = '';
  ui.grid.querySelectorAll('.cloud-terminal-pane').forEach(pane => pane.remove());
  renderTabs(); renderPanes(); controls();
}

async function refresh() {
  if (loading) return workspaceRunning;
  loading = true; controls(); setState('Checking the Amosclaud cloud runtime…');
  try {
    const result = await apiRequest(terminalApi(repositoryId));
    runtimeAvailable = Boolean(result.runtime?.configured && result.runtime?.ok);
    workspaceRunning = Boolean(result.container?.running);
    if (!result.runtime?.configured) setState('Cloud terminal runtime is not configured. Set the runtime URL, public URL, and shared token.', 'not-configured');
    else if (!result.runtime?.ok) setState(result.runtime?.detail || 'Cloud runtime is unreachable.', 'error');
    else if (workspaceRunning) {
      const c = result.container;
      ui.boundary.innerHTML = `<strong>Security boundary:</strong> ${c.user || 'developer'} · ${c.cpu_limit || 2} CPU · ${c.memory_mb || 4096} MB RAM · ${c.pids_limit || 512} processes · network ${c.network || 'none'}.`;
      setState('Cloud workspace is running and repository storage is attached.', 'ready');
      setCloud('Cloud runtime ready', 'connected');
    } else setState('Cloud workspace is ready to start. Repository files remain persistent.', 'stopped');
    return workspaceRunning;
  } catch (error) {
    runtimeAvailable = false; workspaceRunning = false; setState(error.message, 'error'); setCloud('Cloud unavailable', 'error'); return false;
  } finally { loading = false; controls(); }
}

async function startWorkspace() {
  loading = true; controls(); setState('Starting isolated cloud workspace…');
  try {
    const result = await apiRequest(terminalApi(repositoryId, '/start'), { method: 'POST' });
    workspaceRunning = Boolean(result.container?.running);
    setState('Cloud workspace started.', 'ready'); setCloud('Cloud runtime ready', 'connected');
    if (!sessions.size) await createSession();
  } catch (error) { setState(error.message, 'error'); }
  finally { loading = false; controls(); }
}

async function stopWorkspace() {
  loading = true; controls(); setState('Stopping cloud workspace; persistent files will remain…');
  stopAllSessions();
  try {
    await apiRequest(terminalApi(repositoryId, '/stop'), { method: 'POST' });
    workspaceRunning = false; setState('Cloud workspace stopped. Persistent files remain.', 'stopped'); setCloud('Cloud disconnected');
  } catch (error) { setState(error.message, 'error'); }
  finally { loading = false; controls(); }
}

const agentHub = new TerminalAgentHub({
  root: ui.agentHub,
  repositoryId,
  getTerminalContext: () => ({ id: active()?.id || null, profile: active()?.profile || 'bash', output: active()?.outputText(12000) || '' }),
});
agentHub.load();

terminalTab.addEventListener('click', async () => {
  document.querySelectorAll('.ws-tab').forEach(tab => tab.classList.toggle('active', tab === terminalTab));
  document.querySelectorAll('.ws-panel').forEach(item => item.classList.toggle('active', item === panel));
  const running = await refresh();
  if (running && !sessions.size) await createSession();
  else active()?.fit();
});
ui.start.addEventListener('click', startWorkspace);
ui.stop.addEventListener('click', stopWorkspace);
ui.newTerminal.addEventListener('click', () => createSession());
ui.split.addEventListener('click', () => createSession({ split: true }));
ui.reconnect.addEventListener('click', () => active()?.connect());
ui.clear.addEventListener('click', () => active()?.clear());
ui.copy.addEventListener('click', async () => setState(await active()?.copy() ? 'Terminal output copied.' : 'Nothing to copy.', 'ready'));
ui.export.addEventListener('click', () => active()?.exportTranscript());
ui.searchToggle.addEventListener('click', () => { ui.search.hidden = false; ui.searchInput.focus(); });
ui.searchClose.addEventListener('click', () => { ui.search.hidden = true; active()?.focus(); });
ui.searchNext.addEventListener('click', () => active()?.findNext(ui.searchInput.value));
ui.searchPrev.addEventListener('click', () => active()?.findPrevious(ui.searchInput.value));
ui.searchInput.addEventListener('input', () => active()?.findNext(ui.searchInput.value));

document.addEventListener('keydown', event => {
  if (!panel.classList.contains('active') || !event.ctrlKey || !event.shiftKey) return;
  if (event.key === '`') { event.preventDefault(); createSession(); }
  else if (event.key.toLowerCase() === 'f') { event.preventDefault(); ui.search.hidden = false; ui.searchInput.focus(); }
  else if (event.key.toLowerCase() === 'c') { event.preventDefault(); active()?.copy(); }
});

controls();
