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
  let previousObjective = sessionStorage.getItem('amosclaud-agent-previous-objective') || '';

  function publish(name, detail = {}) {
    window.dispatchEvent(new CustomEvent(`amosclaud:${name}`, { detail }));
  }

  const activityToolbar = document.createElement('div');
  activityToolbar.className = 'agent-activity-toolbar';
  activityToolbar.innerHTML = '<strong>Agent plan</strong><button id="btn-toggle-agent-activity" class="btn-agent-activity" type="button" aria-expanded="true">Hide activity</button>';
  controls.insertBefore(activityToolbar, replies);

  const toggleActivityButton = activityToolbar.querySelector('#btn-toggle-agent-activity');
  const stopButton = document.createElement('button');
  stopButton.id = 'btn-stop-agent';
  stopButton.type = 'button';
  stopButton.className = 'btn-stop-agent';
  stopButton.textContent = 'Stop';
  stopButton.hidden = true;
  compose.appendChild(stopButton);

  const phases = ['Receive task', 'Understand objective', 'Inspect evidence', 'Plan safe action', 'Execute task', 'Verify and report'];
  const conversation = JSON.parse(sessionStorage.getItem('amosclaud-agent-conversation') || '[]');

  function saveConversation(role, content) {
    conversation.push({ role, content: String(content).slice(0, 4000) });
    if (conversation.length > 20) conversation.splice(0, conversation.length - 20);
    sessionStorage.setItem('amosclaud-agent-conversation', JSON.stringify(conversation));
  }

  function personalizeGreeting() {
    const user = document.getElementById('current-user');
    const apply = () => {
      const raw = String(user?.textContent || '').trim();
      if (!raw || /loading|sign in/i.test(raw)) return;
      const name = raw.split(/[\s@]/)[0];
      const greeting = replies.querySelector('.agent-reply.muted');
      if (greeting) greeting.textContent = `Welcome ${name}. I’m Amosclaud Autonomous. What can I do for you today?`;
    };
    apply();
    if (user) new MutationObserver(apply).observe(user, { childList: true, subtree: true, characterData: true });
  }

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
    board.innerHTML = `<div class="agent-run-heading"><strong>Task received</strong><span>${new Date().toLocaleTimeString()}</span></div><div class="agent-run-objective"></div><ol class="agent-phase-list"></ol>`;
    board.querySelector('.agent-run-objective').textContent = objective;
    const list = board.querySelector('.agent-phase-list');
    phases.forEach((phase, index) => {
      const item = document.createElement('li');
      item.dataset.phase = String(index);
      item.className = index === 0 ? 'active' : '';
      item.innerHTML = `<span>${index + 1}</span><strong>${phase}</strong><small>${index === 4 && mode !== 'fix' ? 'Execution without file-write permission' : 'Waiting'}</small>`;
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
    publish('agent-phase', { index, phase: phases[index], state, note });
  }

  function flattenPipeline(pipeline, original) {
    const jobs = Array.isArray(pipeline.jobs) ? pipeline.jobs : [];
    const logs = jobs.flatMap(job => Array.isArray(job.logs) ? job.logs : []);
    return {
      ...original,
      status: pipeline.status,
      reply: pipeline.copilot_reply || pipeline.message || original.reply,
      message: pipeline.message,
      logs,
      checks: original.checks || [],
      pipeline_id: pipeline.id || original.pipeline_id,
    };
  }

  function renderResult(data) {
    const failed = String(data.status || '').toLowerCase() === 'failed';
    const result = document.createElement('section');
    result.className = `agent-evidence-card ${failed ? 'failed' : 'success'}`;
    const checks = Array.isArray(data.checks) ? data.checks : [];
    result.innerHTML = `<div class="agent-evidence-heading"><strong>${failed ? 'Execution needs attention' : 'Execution completed'}</strong><span>${data.status || 'complete'}</span></div><p class="agent-result-copy"></p><div class="agent-check-grid"></div><details open><summary>Execution evidence</summary><pre></pre></details>`;
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
    publish('agent-result', data);
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

  function delay(ms) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(resolve, ms);
      controller?.signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Stopped', 'AbortError')); }, { once: true });
    });
  }

  async function pollPipeline(initial, board) {
    if (!initial.pipeline_id || String(initial.pipeline_id).startsWith('conversation-')) return initial;
    let latest = initial;
    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (['success', 'failed', 'cancelled'].includes(String(latest.status || '').toLowerCase())) return latest;
      setBusy(true, latest.status === 'pending' ? 'received' : 'executing');
      setPhase(board, 0, 'complete', 'Task accepted and persisted');
      setPhase(board, 1, 'complete', 'Objective understood');
      setPhase(board, 2, latest.status === 'pending' ? 'active' : 'complete', latest.status === 'pending' ? 'Waiting for execution worker' : 'Repository and runtime inspected');
      setPhase(board, 3, latest.status === 'running' ? 'complete' : 'active', latest.status === 'running' ? 'Execution plan selected' : 'Preparing execution');
      setPhase(board, 4, latest.status === 'running' ? 'active' : '', latest.status === 'running' ? 'Task is executing' : 'Waiting');
      await delay(1000);
      const response = await fetch(`/api/v1/pipelines/${encodeURIComponent(initial.pipeline_id)}`, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      const pipeline = await readResponse(response);
      latest = flattenPipeline(pipeline, initial);
    }
    throw new Error('The task is still running after two minutes. Its pipeline remains available in activity history.');
  }

  async function checkConnections() {
    if (!connectionButton || !connectionStatus) return;
    connectionButton.disabled = true;
    connectionStatus.textContent = 'Checking Autonomous, server, and execution runtime…';
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
    const response = await fetch('/api/v1/agent/run', {
      method: 'POST', signal: controller.signal, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode, objective, branch: 'main',
        metadata: {
          branch: 'main', use_agent: false, apply_changes: mode === 'fix',
          source: 'platform-autonomous-chat', previous_objective: previousObjective,
          conversation: conversation.slice(-12), autonomous_mode_selection: true,
        },
      }),
    });
    return readResponse(response);
  }

  async function sendMessage() {
    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    if (!objective) { objectiveInput.focus(); return; }
    addMessage(objective, 'user');
    saveConversation('user', objective);
    publish('agent-start', { objective, mode });
    const board = addPhaseBoard(mode, objective);
    objectiveInput.value = '';
    controller = new AbortController();
    setBusy(true, 'receiving');
    try {
      let data = await sendAutonomous(mode, objective);
      const isConversation = String(data.pipeline_id || '').startsWith('conversation-');
      if (isConversation && objective.length > 2) {
        previousObjective = objective;
        sessionStorage.setItem('amosclaud-agent-previous-objective', previousObjective);
      }
      if (isConversation) {
        board.remove();
        addMessage(data.reply, 'agent');
        saveConversation('assistant', data.reply);
        setBusy(false, 'ready');
        return;
      }
      data = await pollPipeline(data, board);
      phases.forEach((_, index) => setPhase(board, index, data.status === 'failed' && index === 5 ? 'failed' : 'complete', index === 4 ? 'Execution finished' : index === 5 ? (data.status === 'failed' ? 'Verification found a blocker' : 'Verified evidence recorded') : 'Completed'));
      renderResult(data);
      saveConversation('assistant', data.reply || data.message || 'Task completed.');
      setBusy(false, data.status || 'ready');
    } catch (error) {
      setPhase(board, 5, 'failed', error.name === 'AbortError' ? 'Task stopped' : error.message);
      addMessage(error.name === 'AbortError' ? 'The autonomous task was stopped.' : `Amosclaud could not finish this request: ${error.message}`, 'agent', 'agent-error');
      publish('agent-error', { message: error.name === 'AbortError' ? 'Task stopped by user' : error.message });
      setBusy(false, error.name === 'AbortError' ? 'stopped' : 'error');
    } finally { controller = null; objectiveInput.focus(); }
  }

  toggleActivityButton.addEventListener('click', () => { activityExpanded = !activityExpanded; updateActivityView(); });
  stopButton.addEventListener('click', () => controller?.abort());
  connectionButton?.addEventListener('click', checkConnections);
  document.querySelectorAll('[data-agent-suggestion]').forEach(button => button.addEventListener('click', () => {
    objectiveInput.value = button.dataset.agentSuggestion || '';
    sendMessage();
  }));
  runButton.addEventListener('click', event => { event.preventDefault(); event.stopImmediatePropagation(); sendMessage(); }, true);
  objectiveInput.addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
  objectiveInput.addEventListener('input', () => { objectiveInput.style.height = 'auto'; objectiveInput.style.height = `${Math.min(objectiveInput.scrollHeight, 180)}px`; });
  updateActivityView();
  personalizeGreeting();
})();
