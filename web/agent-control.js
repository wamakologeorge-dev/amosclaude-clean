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
  let activityExpanded = false;

  const activityToolbar = document.createElement('div');
  activityToolbar.className = 'agent-activity-toolbar';
  activityToolbar.innerHTML = `
    <strong>Autonomous activity</strong>
    <button id="btn-toggle-agent-activity" class="btn-agent-activity" type="button" aria-expanded="false">Show activity</button>
  `;
  controls.insertBefore(activityToolbar, replies);

  const toggleActivityButton = activityToolbar.querySelector('#btn-toggle-agent-activity');
  const stopButton = document.createElement('button');
  stopButton.id = 'btn-stop-agent';
  stopButton.type = 'button';
  stopButton.className = 'btn-stop-agent';
  stopButton.textContent = 'Stop';
  stopButton.hidden = true;
  compose.appendChild(stopButton);

  function updateActivityView() {
    replies.classList.toggle('agent-replies-expanded', activityExpanded);
    replies.classList.toggle('agent-replies-collapsed', !activityExpanded);
    toggleActivityButton.textContent = activityExpanded ? 'Hide activity' : 'Show activity';
    toggleActivityButton.setAttribute('aria-expanded', String(activityExpanded));
    const messages = [...replies.querySelectorAll('.agent-reply')];
    messages.forEach((message, index) => {
      message.hidden = !activityExpanded && index !== messages.length - 1;
    });
    requestAnimationFrame(() => {
      replies.scrollTop = replies.scrollHeight;
    });
  }

  function addMessage(text, role = 'agent') {
    replies.querySelector('.agent-reply.muted')?.remove();
    const item = document.createElement('div');
    item.className = `agent-reply chat-message chat-message-${role}`;
    item.textContent = String(text || 'Amosclaud Autonomous completed the request.');
    replies.appendChild(item);
    updateActivityView();
    return item;
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

  function errorText(value, fallback) {
    if (typeof value === 'string' && value.trim()) return value;
    if (value && typeof value === 'object') {
      if (typeof value.msg === 'string') return value.msg;
      if (typeof value.message === 'string') return value.message;
      if (Array.isArray(value)) return value.map(item => errorText(item, '')).filter(Boolean).join('; ');
      try {
        return JSON.stringify(value);
      } catch {
        return fallback;
      }
    }
    return fallback;
  }

  async function readResponse(response) {
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();
    let data = {};

    if (raw && contentType.includes('application/json')) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { detail: 'The server returned invalid JSON.' };
      }
    } else if (raw) {
      data = { detail: raw };
    }

    if (!response.ok) {
      throw new Error(errorText(data.detail || data.message, `Request failed (${response.status})`));
    }
    return data;
  }

  async function checkConnections() {
    if (!connectionButton || !connectionStatus) return;
    connectionButton.disabled = true;
    connectionStatus.textContent = 'Checking Amosclaud Autonomous…';
    try {
      const [healthResponse, profileResponse] = await Promise.all([
        fetch('/health', { credentials: 'same-origin', cache: 'no-store' }),
        fetch('/api/v1/agent', { credentials: 'same-origin', cache: 'no-store' }),
      ]);
      const health = await readResponse(healthResponse);
      const profile = await readResponse(profileResponse);
      connectionStatus.textContent = `${profile.name || 'Amosclaud Autonomous Runtime'} is online. Server healthy: ${health.status || 'ok'}.`;
    } catch (error) {
      connectionStatus.textContent = `Platform needs attention: ${error.message}`;
    } finally {
      connectionButton.disabled = false;
    }
  }

  async function sendAutonomous(mode, objective) {
    const response = await fetch('/api/v1/agent/run', {
      method: 'POST',
      signal: controller.signal,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode,
        objective,
        branch: 'main',
        metadata: {
          branch: 'main',
          use_agent: false,
          source: 'platform-autonomous',
        },
      }),
    });
    return readResponse(response);
  }

  async function sendMessage() {
    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    if (!objective) {
      objectiveInput.focus();
      return;
    }

    addMessage(objective, 'user');
    objectiveInput.value = '';
    objectiveInput.style.height = '';
    controller = new AbortController();
    setBusy(true, 'working');
    const pending = addMessage('Amosclaud Autonomous is working on your request…', 'pending');

    try {
      const data = await sendAutonomous(mode, objective);
      pending.remove();
      const checks = Array.isArray(data.checks) && data.checks.length
        ? `\n\nChecks: ${data.checks.map(check => `${check.name}: ${check.status}`).join(', ')}`
        : '';
      addMessage(`${data.reply || data.message || 'Amosclaud Autonomous completed the request.'}${checks}`);
      setBusy(false, data.status || 'ready');
    } catch (error) {
      pending.remove();
      if (error.name !== 'AbortError') {
        addMessage(`Amosclaud Autonomous could not finish this request: ${error.message}`);
        setBusy(false, 'error');
      }
    } finally {
      controller = null;
      objectiveInput.focus();
    }
  }

  toggleActivityButton.addEventListener('click', () => {
    activityExpanded = !activityExpanded;
    updateActivityView();
  });

  stopButton.addEventListener('click', () => {
    controller?.abort();
    controller = null;
    setBusy(false, 'stopped');
    addMessage('The autonomous request was stopped.');
    objectiveInput.focus();
  });

  connectionButton?.addEventListener('click', checkConnections);
  runButton.addEventListener('click', event => {
    event.preventDefault();
    event.stopImmediatePropagation();
    sendMessage();
  }, true);

  objectiveInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  });

  objectiveInput.addEventListener('input', () => {
    objectiveInput.style.height = 'auto';
    objectiveInput.style.height = `${Math.min(objectiveInput.scrollHeight, 180)}px`;
  });

  updateActivityView();
})();