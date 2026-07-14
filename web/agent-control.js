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
  const sessionStorageKey = 'amosclaud-chat-session';
  let chatSessionId = sessionStorage.getItem(sessionStorageKey) || null;
  let controller = null;
  let activityExpanded = false;

  const activityToolbar = document.createElement('div');
  activityToolbar.className = 'agent-activity-toolbar';
  activityToolbar.innerHTML = `
    <strong>Agent activity</strong>
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
    item.textContent = text;
    replies.appendChild(item);
    updateActivityView();
    return item;
  }

  function addActionLink(url, label) {
    if (!url || !url.startsWith('/')) return;
    const item = document.createElement('div');
    item.className = 'agent-reply chat-message chat-message-agent';
    const link = document.createElement('a');
    link.className = 'btn-primary';
    link.href = url;
    link.textContent = label;
    item.appendChild(link);
    replies.appendChild(item);
    updateActivityView();
  }

  function statusClass(label, busy) {
    if (busy) return 'badge-running';
    const normalized = String(label || '').toLowerCase();
    if (['failed', 'error', 'cancelled', 'offline'].includes(normalized)) return 'badge-failed';
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
      throw new Error(data.detail || data.message || `Request failed (${response.status})`);
    }

    return data;
  }

  async function checkConnections() {
    if (!connectionButton || !connectionStatus) return;

    connectionButton.disabled = true;
    connectionStatus.textContent = 'Checking Amosclaud platform services…';

    try {
      const [healthResponse, profileResponse] = await Promise.all([
        fetch('/health', { credentials: 'same-origin', cache: 'no-store' }),
        fetch('/api/v1/agent', { credentials: 'same-origin', cache: 'no-store' }),
      ]);

      const health = await readResponse(healthResponse);
      const profile = await readResponse(profileResponse);
      connectionStatus.textContent = `Runtime ready — ${profile.name || 'Amosclaud Autonomous Runtime'} is online. Server healthy: ${health.status || 'ok'}. Ask mode remains available through the platform chat service.`;
    } catch (error) {
      connectionStatus.textContent = `Platform needs attention: ${error.message}`;
    } finally {
      connectionButton.disabled = false;
    }
  }

  async function sendAsk(objective) {
    const response = await fetch('/api/chat', {
      method: 'POST',
      signal: controller.signal,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: objective,
        session_id: chatSessionId,
        start_pr_task: false,
        base_branch: 'main',
      }),
    });

    const data = await readResponse(response);
    if (data.session_id) {
      chatSessionId = data.session_id;
      sessionStorage.setItem(sessionStorageKey, chatSessionId);
    }
    return data;
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
          source: 'platform-assistant',
        },
      }),
    });

    return readResponse(response);
  }

  async function sendMessage() {
    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    const conversational = mode === 'autonomous-check';

    if (!objective) {
      objectiveInput.focus();
      return;
    }

    addMessage(objective, 'user');
    objectiveInput.value = '';
    objectiveInput.style.height = '';

    controller = new AbortController();
    setBusy(true, conversational ? 'thinking' : 'working');
    const pending = addMessage(
      conversational ? 'Amosclaud is thinking…' : 'Amosclaud Autonomous is working on your request…',
      'pending',
    );

    try {
      const data = conversational
        ? await sendAsk(objective)
        : await sendAutonomous(mode, objective);

      pending.remove();

      const checks = Array.isArray(data.checks) && data.checks.length
        ? `\n\nChecks: ${data.checks.map(check => `${check.name}: ${check.status}`).join(', ')}`
        : '';

      addMessage(`${data.reply || 'Amosclaud completed the request.'}${checks}`);

      if (data.task_url && data.task_status === 'completed') {
        addActionLink(data.task_url, 'Open created repository');
      }

      setBusy(false, data.status || data.task_status || 'ready');
    } catch (error) {
      pending.remove();
      if (error.name !== 'AbortError') {
        addMessage(`Amosclaud could not finish this request: ${error.message}`);
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
    addMessage('The request was stopped.');
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