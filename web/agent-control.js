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

  const activityToolbar = document.createElement('div');
  activityToolbar.className = 'agent-activity-toolbar';
  activityToolbar.innerHTML = `
    <strong>Autonomous activity</strong>
    <button id="btn-toggle-agent-activity" class="btn-agent-activity" type="button" aria-expanded="false">Show activity</button>
  `;
  controls.insertBefore(activityToolbar, replies);

  const toggleActivityButton = activityToolbar.querySelector('#btn-toggle-agent-activity');
  let activityExpanded = false;

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
    requestAnimationFrame(() => { replies.scrollTop = replies.scrollHeight; });
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

  function setBusy(busy, label = 'autonomous') {
    runButton.disabled = busy;
    stopButton.hidden = !busy;
    compose.classList.toggle('agent-is-busy', busy);
    if (statusBadge) {
      statusBadge.className = `badge ${busy ? 'badge-running' : 'badge-success'}`;
      statusBadge.textContent = label;
    }
  }

  async function readResponse(response) {
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw }; }
    if (!response.ok) {
      throw new Error(data.detail || data.message || `Request failed (${response.status})`);
    }
    return data;
  }

  async function checkConnections() {
    if (!connectionButton || !connectionStatus) return;
    connectionButton.disabled = true;
    connectionStatus.textContent = 'Checking Amosclaud Autonomous Runtime…';
    try {
      const [healthResponse, profileResponse] = await Promise.all([
        fetch('/health', { credentials: 'same-origin', cache: 'no-store' }),
        fetch('/api/v1/agent', { credentials: 'same-origin', cache: 'no-store' }),
      ]);
      const health = await readResponse(healthResponse);
      const profile = await readResponse(profileResponse);
      connectionStatus.textContent = `Ready — ${profile.name || 'Amosclaud Autonomous Runtime'} is online. Health: ${health.status || 'ok'}. AI model access is optional.`;
    } catch (error) {
      connectionStatus.textContent = `Runtime needs attention: ${error.message}`;
    } finally {
      connectionButton.disabled = false;
    }
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
    setBusy(true, mode === 'autonomous-check' ? 'thinking' : 'working');
    const pending = addMessage('Amosclaud Autonomous is processing your request…', 'pending');

    try {
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
      const data = await readResponse(response);
      pending.remove();
      const checks = Array.isArray(data.checks) && data.checks.length
        ? `\n\nChecks: ${data.checks.map(check => `${check.name}: ${check.status}`).join(', ')}`
        : '';
      addMessage(`${data.reply || 'Amosclaud Autonomous completed the request.'}${checks}`);
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
