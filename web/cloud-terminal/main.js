import { apiRequest, repositoryIdFromLocation, terminalApi } from './api.js';
import { TerminalAgentHub } from './agent-hub.js';
import { ProjectToolbelt } from './project-tools.js';
import { CloudTerminalSession } from './session.js';
import { WorkspaceFeatureCells } from './workspace-features.js';

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
addStyle('/static/cloud-terminal/project-tools.css', 'data-amosclaud-project-tools-style');
addStyle('/static/cloud-terminal/workspace-features.css', 'data-amosclaud-workspace-features-style');
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
      <h2>Amosclaud developer terminal</h2>
      <p>Start one workspace, watch commands run live, debug interactively, inspect ports and problems, commit, and safely sync GitHub.</p>
    </div>
    <div class="ws-tool-form">
      <button data-start type="button">Start workspace</button>
      <button data-stop type="button" disabled>Stop workspace</button>
    </div>
  </div>
  <div data-boundary class="ws-full-editor-note"><strong>Runtime:</strong> checking the Amosclaud execution connection…</div>
  <div class="ws-full-editor-note"><strong>Full developer terminal:</strong> writable repository · nano and vim · Git · Python · Node.js and npm · C/C++ · run and interactive debug tools · tmux · port and network diagnostics. Run <code>amos help</code> for built-in tools.</div>
  <p data-state class="ws-status" role="status" aria-live="polite">Open this tab to connect to the Amosclaud runtime.</p>
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
      <span data-cloud class="cloud-terminal-cloud-state">Connecting…</span>
    </div>
    <div class="cloud-terminal-tabs" data-tabs></div>
    <div class="cloud-terminal-search" data-search hidden>
      <input data-search-input type="search" placeholder="Search terminal output" />
      <button data-search-prev type="button">Previous</button>
      <button data-search-next type="button">Next</button>
      <button data-search-close type="button">Close</button>
    </div>
    <section class="terminal-project-tools" data-project-tools aria-label="Project tools"></section>
    <section class="workspace-feature-cells" data-workspace-features aria-label="Ports problems connectors and network"></section>
    <section class="terminal-live-activity idle" data-live-activity aria-live="polite">
      <span class="terminal-live-dot" aria-hidden="true"></span>
      <div class="terminal-live-copy">
        <strong data-activity-title>Runtime idle</strong>
        <code data-activity-command>Start the workspace, then choose Run app or Debug.</code>
      </div>
      <span class="terminal-live-time" data-activity-time>0s</span>
      <button data-activity-stop type="button" disabled>Stop process</button>
    </section>
    <div class="cloud-terminal-workbench">
      <div class="cloud-terminal-grid" data-grid><div class="cloud-terminal-empty" data-empty>Start the workspace to create a live terminal.</div></div>
      <aside class="terminal-agent-hub" data-agent-hub></aside>
    </div>
    <p class="cloud-terminal-shortcuts"><kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>\`</kbd> new terminal · <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>F</kbd> search · <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>C</kbd> copy · <kbd>Ctrl</kbd>+<kbd>C</kbd> stop a running process</p>
  </div>`;
main.appendChild(panel);

const q = selector => panel.querySelector(selector);
const ui = {
  start: q('[data-start]'), stop: q('[data-stop]'), boundary: q('[data-boundary]'), state: q('[data-state]'),
  profile: q('[data-profile]'), newTerminal: q('[data-new]'), split: q('[data-split]'), reconnect: q('[data-reconnect]'),
  searchToggle: q('[data-search-toggle]'), copy: q('[data-copy]'), export: q('[data-export]'), clear: q('[data-clear]'),
  cloud: q('[data-cloud]'), tabs: q('[data-tabs]'), search: q('[data-search]'), searchInput: q('[data-search-input]'),
  searchPrev: q('[data-search-prev]'), searchNext: q('[data-search-next]'), searchClose: q('[data-search-close]'),
  grid: q('[data-grid]'), empty: q('[data-empty]'), agentHub: q('[data-agent-hub]'), projectTools: q('[data-project-tools]'),
  workspaceFeatures: q('[data-workspace-features]'), liveActivity: q('[data-live-activity]'),
  activityTitle: q('[data-activity-title]'), activityCommand: q('[data-activity-command]'),
  activityTime: q('[data-activity-time]'), activityStop: q('[data-activity-stop]'),
};

const sessions = new Map();
let loading = false;
let runtimeAvailable = false;
let runtimeProvider = '';
let workspaceRunning = false;
let activeId = '';
let splitId = '';
let counter = 0;
let maxSessions = 8;
let liveActivity = null;
let activityTimer = null;

function makeId() {
  const bytes = new Uint8Array(8);
  crypto.getRandomValues(bytes);
  return `term_${Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')}`;
}
function active() { return sessions.get(activeId) || null; }
function visible(id) { return id === activeId || id === splitId; }
function setState(message, kind = '') { ui.state.textContent = message; ui.state.dataset.state = kind; }
function setCloud(message, kind = '') { ui.cloud.textContent = message; ui.cloud.className = `cloud-terminal-cloud-state${kind ? ` ${kind}` : ''}`; }

function elapsed(startedAt, finishedAt = Date.now()) {
  const seconds = Math.max(0, Math.floor((finishedAt - startedAt) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function stopActivityTimer() {
  if (activityTimer) clearInterval(activityTimer);
  activityTimer = null;
}

function renderActivity(activity) {
  liveActivity = activity;
  stopActivityTimer();
  if (!activity) {
    ui.liveActivity.className = 'terminal-live-activity idle';
    ui.activityTitle.textContent = 'Runtime idle';
    ui.activityCommand.textContent = workspaceRunning
      ? 'Choose Run app, Debug, or any project command.'
      : 'Start the workspace, then choose Run app or Debug.';
    ui.activityTime.textContent = '0s';
    ui.activityStop.disabled = true;
    return;
  }
  const states = {
    running: ['Running now', 'running'],
    stopping: ['Stopping process…', 'stopping'],
    success: ['Completed successfully', 'success'],
    failed: [`Exited with code ${activity.status ?? 1}`, 'failed'],
    interrupted: ['Process stopped', 'interrupted'],
  };
  const [title, className] = states[activity.state] || ['Runtime activity', activity.state || 'idle'];
  ui.liveActivity.className = `terminal-live-activity ${className}`;
  ui.activityTitle.textContent = title;
  ui.activityCommand.textContent = activity.command || 'Terminal command';
  ui.activityTime.textContent = elapsed(activity.startedAt, activity.finishedAt || Date.now());
  ui.activityStop.disabled = !['running', 'stopping'].includes(activity.state);
  if (activity.state === 'running' || activity.state === 'stopping') {
    activityTimer = setInterval(() => {
      ui.activityTime.textContent = elapsed(activity.startedAt);
    }, 1000);
  }
}

function onTerminalActivity(session, activity) {
  renderActivity(activity);
  if (activity.state === 'running') {
    setState(`Running in ${session.title}: ${activity.command}`, 'ready');
  } else if (activity.state === 'success') {
    setState(`Command completed successfully in ${elapsed(activity.startedAt, activity.finishedAt)}.`, 'ready');
    projectTools.load();
  } else if (activity.state === 'failed') {
    setState(`Command exited with code ${activity.status}. Review the terminal output or send it to Amosclaud Doctor.`, 'error');
  } else if (activity.state === 'interrupted') {
    setState('The running process was stopped.', 'stopped');
  }
}

function controls() {
  const has = Boolean(active());
  ui.start.disabled = loading || !runtimeAvailable || workspaceRunning;
  ui.stop.disabled = loading || !runtimeAvailable || !workspaceRunning;
  ui.newTerminal.disabled = loading || !workspaceRunning || sessions.size >= maxSessions;
  ui.split.disabled = loading || !workspaceRunning || !has || sessions.size >= maxSessions;
  ui.reconnect.disabled = loading || !workspaceRunning || !has;
  for (const button of [ui.searchToggle, ui.copy, ui.export, ui.clear]) button.disabled = !has;
  projectTools?.setWorkspaceRunning?.(workspaceRunning);
  featureCells?.updateAvailability?.();
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
  const connectedSessions = [...sessions.values()].filter(item => item.state === 'connected');
  if (connectedSessions.length) {
    const managed = connectedSessions.some(item => item.provider === 'managed');
    setCloud(
      `${managed ? 'Managed runtime connected' : 'Isolated runtime connected'} · ${connectedSessions.length} terminal${connectedSessions.length === 1 ? '' : 's'}`,
      'connected',
    );
  } else {
    setCloud(workspaceRunning ? 'Runtime ready · terminal disconnected' : 'Workspace stopped', state === 'error' ? 'error' : '');
  }
  if (session.id === activeId && detail) setState(detail, state === 'connected' ? 'ready' : state === 'error' ? 'error' : '');
}

async function createSession({ profile = ui.profile.value, split = false } = {}) {
  if (!workspaceRunning || sessions.size >= maxSessions) return null;
  const id = makeId();
  counter += 1;
  const session = new CloudTerminalSession({
    repositoryId,
    id,
    profile,
    title: `${profile} ${counter}`,
    onState: onSessionState,
    onFocus: item => activateSession(item.id, false),
    onActivity: onTerminalActivity,
  });
  sessions.set(id, session);
  const pane = document.createElement('div'); pane.className = 'cloud-terminal-pane'; pane.dataset.terminalId = id; ui.grid.appendChild(pane);
  await session.mount(pane);
  if (split && activeId) splitId = id;
  activeId = id;
  renderTabs(); renderPanes(); controls();
  await session.connect().catch(error => setState(error.message, 'error'));
  return session;
}

async function ensureTerminal() {
  return active() || createSession();
}

async function ensureCommandTerminal() {
  const current = active();
  if (current && current.profile !== 'python') return current;
  return createSession({ profile: 'bash' });
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
  if (liveActivity?.terminalId === id && ['running', 'stopping'].includes(liveActivity.state)) {
    renderActivity({ ...liveActivity, state: 'interrupted', finishedAt: Date.now() });
  }
  renderTabs(); renderPanes(); controls();
}

function stopAllSessions() {
  sessions.forEach(session => session.dispose());
  sessions.clear(); activeId = ''; splitId = '';
  ui.grid.querySelectorAll('.cloud-terminal-pane').forEach(pane => pane.remove());
  renderActivity(null);
  renderTabs(); renderPanes(); controls();
}

function describeBoundary(container, provider) {
  if (provider === 'managed') {
    return '<strong>Managed runtime:</strong> same Amosclaud deployment · non-root terminal process · scrubbed secrets · persistent repository · live WebSocket output.';
  }
  return `<strong>Isolated runtime:</strong> ${container.user || 'developer'} · ${container.cpu_limit || 2} CPU · ${container.memory_mb || 4096} MB RAM · ${container.pids_limit || 512} processes · network ${container.network || 'none'}.`;
}

async function refresh() {
  if (loading) return workspaceRunning;
  loading = true; controls(); setState('Checking the Amosclaud runtime…');
  try {
    const result = await apiRequest(terminalApi(repositoryId));
    runtimeAvailable = Boolean(result.runtime?.configured && result.runtime?.ok);
    runtimeProvider = result.container?.provider || result.provider || result.runtime?.provider || '';
    workspaceRunning = Boolean(result.container?.running);
    maxSessions = runtimeProvider === 'managed' ? 4 : 8;
    featureCells.setRuntime(result.container || { running: false, network: result.runtime?.network || 'unknown' });
    ui.boundary.innerHTML = describeBoundary(result.container || {}, runtimeProvider || result.runtime?.provider);
    if (!runtimeAvailable) {
      setState(result.runtime?.detail || 'The terminal runtime is not available.', 'error');
      setCloud('Runtime unavailable', 'error');
    } else if (workspaceRunning) {
      setState(`${runtimeProvider === 'managed' ? 'Managed' : 'Isolated'} workspace is running. Commands and debugger output will stream live below.`, 'ready');
      setCloud(`${runtimeProvider === 'managed' ? 'Managed' : 'Isolated'} runtime ready`, 'connected');
    } else {
      setState('Runtime connected. Tap Start workspace once to begin.', 'stopped');
      setCloud(`${result.runtime?.provider === 'managed' ? 'Managed' : 'Isolated'} runtime ready`, 'connected');
    }
    renderActivity(liveActivity);
    return workspaceRunning;
  } catch (error) {
    runtimeAvailable = false;
    workspaceRunning = false;
    featureCells.setRuntime({ running: false, network: 'unavailable' });
    setState(`${error.message} Reload after the deployment finishes, then tap Start workspace.`, 'error');
    setCloud('Connection needs retry', 'error');
    return false;
  } finally {
    loading = false;
    controls();
  }
}

async function startWorkspace() {
  loading = true; controls(); setState('Starting the Amosclaud developer workspace…');
  try {
    const result = await apiRequest(terminalApi(repositoryId, '/start'), { method: 'POST' });
    runtimeProvider = result.provider || result.container?.provider || 'managed';
    workspaceRunning = Boolean(result.container?.running);
    maxSessions = runtimeProvider === 'managed' ? 4 : 8;
    featureCells.setRuntime(result.container || { running: workspaceRunning, network: 'unknown' });
    ui.boundary.innerHTML = describeBoundary(result.container || {}, runtimeProvider);
    setState('Workspace started. The terminal is connecting now; run and debug output will appear live.', 'ready');
    setCloud(`${runtimeProvider === 'managed' ? 'Managed' : 'Isolated'} runtime ready`, 'connected');
    if (!sessions.size) await createSession({ profile: 'bash' });
    await Promise.all([projectTools.load(), featureCells.load()]);
    renderActivity(null);
  } catch (error) {
    setState(error.message, 'error');
    setCloud('Start failed', 'error');
  } finally {
    loading = false;
    controls();
  }
}

async function stopWorkspace() {
  loading = true; controls(); setState('Stopping the workspace; persistent files will remain…');
  stopAllSessions();
  try {
    await apiRequest(terminalApi(repositoryId, '/stop'), { method: 'POST' });
    workspaceRunning = false;
    featureCells.setRuntime({ running: false, network: featureCells.runtime?.network || 'none' });
    setState('Workspace stopped. Files and commits remain saved.', 'stopped');
    setCloud('Workspace stopped');
  } catch (error) {
    setState(error.message, 'error');
  } finally {
    loading = false;
    controls();
  }
}

const projectTools = new ProjectToolbelt({
  root: ui.projectTools,
  repositoryId,
  ensureTerminal: ensureCommandTerminal,
  isWorkspaceRunning: () => workspaceRunning,
});
projectTools.load();

const featureCells = new WorkspaceFeatureCells({
  root: ui.workspaceFeatures,
  repositoryId,
  ensureTerminal: ensureCommandTerminal,
  isWorkspaceRunning: () => workspaceRunning,
  focusAgentHub: () => {
    ui.agentHub.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    ui.agentHub.querySelector('textarea, input, button')?.focus();
  },
});
featureCells.load();

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
  await Promise.all([projectTools.load(), featureCells.load()]);
  if (running && !sessions.size) await createSession({ profile: 'bash' });
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
ui.activityStop.addEventListener('click', () => {
  const session = sessions.get(liveActivity?.terminalId) || active();
  session?.interrupt();
});

document.addEventListener('keydown', event => {
  if (!panel.classList.contains('active') || !event.ctrlKey || !event.shiftKey) return;
  if (event.key === '`') { event.preventDefault(); createSession(); }
  else if (event.key.toLowerCase() === 'f') { event.preventDefault(); ui.search.hidden = false; ui.searchInput.focus(); }
  else if (event.key.toLowerCase() === 'c') { event.preventDefault(); active()?.copy(); }
});

renderActivity(null);
controls();
