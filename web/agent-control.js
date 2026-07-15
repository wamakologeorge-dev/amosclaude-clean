(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const modeInput = document.getElementById('agent-mode-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  const connectionButton = document.getElementById('btn-check-agent-connections');
  const connectionStatus = document.getElementById('agent-connection-status');
  if (!runButton || !objectiveInput || !modeInput || !replies) return;

  const compose = runButton.closest('.agent-compose');
  const controls = replies.parentElement;
  let controller = null;
  let activityExpanded = true;

  const activityToolbar = document.createElement('div');
  activityToolbar.className = 'agent-activity-toolbar';
  activityToolbar.innerHTML = '<strong>Agent console</strong><button id="btn-toggle-agent-activity" class="btn-agent-activity" type="button" aria-expanded="true">Hide activity</button>';
  controls.insertBefore(activityToolbar, replies);

  const toggleActivityButton = activityToolbar.querySelector('#btn-toggle-agent-activity');
  const stopButton = document.createElement('button');
  stopButton.id = 'btn-stop-agent';
  stopButton.type = 'button';
  stopButton.className = 'btn-stop-agent';
  stopButton.textContent = 'Stop';
  stopButton.hidden = true;
  compose.appendChild(stopButton);

  const phases = ['Understand objective', 'Inspect evidence', 'Plan safe action', 'Act when authorized', 'Verify result', 'Report evidence'];

  function updateActivityView() {
    replies.classList.toggle('agent-replies-expanded', activityExpanded);
    replies.classList.toggle('agent-replies-collapsed', !activityExpanded);
    toggleActivityButton.textContent = activityExpanded ? 'Hide activity' : 'Show activity';
    toggleActivityButton.setAttribute('aria-expanded', String(activityExpanded));
    const messages = [...replies.querySelectorAll('.agent-reply')];
    messages.forEach((message, index) => { message.hidden = !activityExpanded && index !== messages.length - 1; });
    requestAnimationFrame(() => { replies.scrollTop = replies.scrollHeight; });
  }

  function addMessage(text, role = 'agent', extraClass = '') {
    replies.querySelector('.agent-reply.muted')?.remove();
    const item = document.createElement('div');
    item.className = `agent-reply chat-message chat-message-${role} ${extraClass}`.trim();
    item.textContent = String(text || 'Amosclaud completed the request.');
    replies.appendChild(item);
    updateActivityView();
    return item;
  }

  function addPhaseBoard(mode, objective) {
    const board = document.createElement('section');
    board.className = 'agent-run-card';
    board.innerHTML = `<div class="agent-run-heading"><strong>Task started</strong><span>${new Date().toLocaleTimeString()}</span></div><div class="agent-run-objective"></div><ol class="agent-phase-list"></ol>`;
    board.querySelector('.agent-run-objective').textContent = objective;
    const list = board.querySelector('.agent-phase-list');
    phases.forEach((phase, index) => {
      const item = document.createElement('li');
      item.dataset.phase = String(index);
      item.className = index === 0 ? 'active' : '';
      item.innerHTML = `<span>${index + 1}</span><strong>${phase}</strong><small>${index === 3 && mode !== 'fix' ? 'No file writes authorized' : 'Waiting'}</small>`;
      list.appendChild(item);
    });
    replies.appendChild(board);
    updateActivityView();
    return board;
  }

  function setPhase(board, index, state, note) {
    const item = board?.querySelector(`[data-phase="${index}"]`);
    if (!item) return;
    item.className = state;
    item.querySelector('small').textContent = note;
  }

  function renderResult(data, board) {
    phases.forEach((_, index) => setPhase(board, index, 'complete', index === 3 ? (data.mode === 'fix' ? 'Authorized action completed' : 'No write action required') : 'Completed'));
    const result = document.createElement('section');
    result.className = `agent-evidence-card ${String(data.status || '').toLowerCase() === 'failed' ? 'failed' : 'success'}`;
    const checks = Array.isArray(data.checks) ? data.checks : [];
    result.innerHTML = `<div class="agent-evidence-heading"><strong>${data.status === 'failed' ? 'Needs attention' : 'Verified result'}</strong><span>${data.status || 'complete'}</span></div><p class="agent-result-copy"></p><div class="agent-check-grid"></div><details><summary>Technical evidence</summary><pre></pre></details>`;
    result.querySelector('.agent-result-copy').textContent = data.reply || data.message || 'Task completed.';
    const grid = result.querySelector('.agent-check-grid');
    checks.forEach(check => {
      const row = document.createElement('div');
      row.className = `agent-check ${check.status || 'unknown'}`;
      row.innerHTML = '<span></span><div><strong></strong><small></small></div>';
      row.querySelector('span').textContent = check.status === 'passed' ? '✓' : check.status === 'failed' ? '×' : '!';
      row.querySelector('strong').textContent = check.name || 'check';
      row.querySelector('small').textContent = check.summary || check.status || 'No summary';
      grid.appendChild(row);
    });
    result.querySelector('pre').textContent = (Array.isArray(data.logs) ? data.logs : []).join('\n') || 'No additional logs returned.';
    replies.appendChild(result);
    updateActivityView();
  }

  function statusClass(label, busy) {
    if (busy) return 'badge-running';
    const normalized = String(label || '').toLowerCase();
    if (['failed', 'error', 'cancelled', 'offline', 'stopped'].includes(normalized)) return 'badge-failed';
    if (['pending', 'queued', 'waiting'].includes(normalized)) return 'badge-pending';
    if (['running', 'active', 'working', 'thinking', 'in_progress'].includes(normalized)) return 'badge-running';
    return 'badge-success';
  }

  function setBusy(busy, label = 'ready') {
    runButton.disabled = busy;
    stopButton.hidden = !busy;
    compose.classList.toggle('agent-is-busy', busy);
    if (statusBadge) {
      statusBadge.className = `badge ${statusClass(label, busy)}`;
      statusBadge.textContent = label;
    }
  }

  async function readResponse(response) {
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw || 'Invalid server response' }; }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    return data;
  }

  async function checkConnections() {
    if (!connectionButton || !connectionStatus) return;
    connectionButton.disabled = true;
    connectionStatus.textContent = 'Checking agent, server, and model runtime…';
    try {
      const [healthResponse, profileResponse] = await Promise.all([
        fetch('/health', { credentials: 'same-origin', cache: 'no-store' }),
        fetch('/api/v1/agent', { credentials: 'same-origin', cache: 'no-store' }),
      ]);
      const health = await readResponse(healthResponse);
      const profile = await readResponse(profileResponse);
      connectionStatus.textContent = `${profile.name || 'Amosclaud Autonomous Agent'} is online. Server: ${health.status || 'ok'}.`;
    } catch (error) {
      connectionStatus.textContent = `Platform needs attention: ${error.message}`;
    } finally { connectionButton.disabled = false; }
  }

  async function sendAutonomous(mode, objective) {
    const agentMode = mode === 'build' || mode === 'fix';
    const response = await fetch('/api/v1/agent/run', {
      method: 'POST', signal: controller.signal, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode, objective, branch: 'main',
        metadata: { branch: 'main', use_agent: agentMode, apply_changes: mode === 'fix', source: 'platform-agent-console' },
      }),
    });
    return readResponse(response);
  }

  async function sendMessage() {
    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    if (!objective) { objectiveInput.focus(); return; }
    addMessage(objective, 'user');
    const board = addPhaseBoard(mode, objective);
    objectiveInput.value = '';
    controller = new AbortController();
    setBusy(true, 'working');
    setPhase(board, 0, 'complete', 'Objective accepted');
    setPhase(board, 1, 'active', 'Reading repository and runtime evidence');
    try {
      const data = await sendAutonomous(mode, objective);
      setPhase(board, 1, 'complete', 'Evidence inspected');
      setPhase(board, 2, 'complete', mode === 'autonomous-check' ? 'Inspection plan completed' : 'Safe plan prepared');
      setPhase(board, 3, 'complete', mode === 'fix' ? 'Authorized changes processed' : 'No write authorization used');
      setPhase(board, 4, data.status === 'failed' ? 'failed' : 'complete', data.status === 'failed' ? 'Verification found a blocker' : 'Verification passed');
      setPhase(board, 5, 'complete', 'Evidence reported');
      renderResult(data, board);
      setBusy(false, data.status || 'ready');
    } catch (error) {
      setPhase(board, 4, 'failed', error.name === 'AbortError' ? 'Task stopped' : error.message);
      addMessage(error.name === 'AbortError' ? 'The agent task was stopped.' : `Amosclaud could not finish this request: ${error.message}`, 'agent', 'agent-error');
      setBusy(false, error.name === 'AbortError' ? 'stopped' : 'error');
    } finally { controller = null; objectiveInput.focus(); }
  }

  toggleActivityButton.addEventListener('click', () => { activityExpanded = !activityExpanded; updateActivityView(); });
  stopButton.addEventListener('click', () => controller?.abort());
  connectionButton?.addEventListener('click', checkConnections);
  runButton.addEventListener('click', event => { event.preventDefault(); event.stopImmediatePropagation(); sendMessage(); }, true);
  objectiveInput.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
  objectiveInput.addEventListener('input', () => { objectiveInput.style.height = 'auto'; objectiveInput.style.height = `${Math.min(objectiveInput.scrollHeight, 180)}px`; });
  updateActivityView();
})();