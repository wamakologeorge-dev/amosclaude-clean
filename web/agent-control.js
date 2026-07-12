(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const modeInput = document.getElementById('agent-mode-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  if (!runButton || !objectiveInput || !modeInput || !replies) return;

  const compose = runButton.closest('.agent-compose');
  const controls = replies.parentElement;

  const activityToolbar = document.createElement('div');
  activityToolbar.className = 'agent-activity-toolbar';
  activityToolbar.innerHTML = `
    <strong>Agent activity</strong>
    <button id="btn-toggle-agent-activity" class="btn-agent-activity" type="button" aria-expanded="false">Show activity</button>
  `;
  controls.insertBefore(activityToolbar, replies);

  const toggleActivityButton = activityToolbar.querySelector('#btn-toggle-agent-activity');
  let activityExpanded = false;

  const stopButton = document.createElement('button');
  stopButton.id = 'btn-stop-agent';
  stopButton.type = 'button';
  stopButton.className = 'btn-stop-agent';
  stopButton.textContent = 'Stop Agent';
  stopButton.hidden = true;
  compose.appendChild(stopButton);

  let controller = null;
  const greetingWords = new Set(['hi', 'hello', 'hey', 'hiya', 'yo', 'good morning', 'good afternoon', 'good evening']);

  function developerName() {
    const raw = document.getElementById('current-user')?.textContent?.trim() || 'Developer';
    return raw.split(/\s+/)[0] || 'Developer';
  }

  function updateActivityView() {
    replies.classList.toggle('agent-replies-expanded', activityExpanded);
    replies.classList.toggle('agent-replies-collapsed', !activityExpanded);
    toggleActivityButton.textContent = activityExpanded ? 'Hide activity' : 'Show activity';
    toggleActivityButton.setAttribute('aria-expanded', String(activityExpanded));

    const messages = [...replies.querySelectorAll('.agent-reply')];
    messages.forEach((message, index) => {
      const isNewest = index === messages.length - 1;
      message.hidden = !activityExpanded && !isNewest;
    });

    requestAnimationFrame(() => {
      replies.scrollTop = replies.scrollHeight;
    });
  }

  toggleActivityButton.addEventListener('click', () => {
    activityExpanded = !activityExpanded;
    updateActivityView();
  });

  function addMessage(text, role = 'agent') {
    const placeholder = replies.querySelector('.agent-reply.muted');
    if (placeholder) placeholder.remove();

    const item = document.createElement('div');
    item.className = `agent-reply chat-message chat-message-${role}`;
    item.textContent = text;
    replies.appendChild(item);
    updateActivityView();
    return item;
  }

  function setBusy(busy, label = 'ready') {
    runButton.disabled = busy;
    stopButton.hidden = !busy;
    compose.classList.toggle('agent-is-busy', busy);
    if (statusBadge) {
      statusBadge.className = `badge ${busy ? 'badge-running' : 'badge-success'}`;
      statusBadge.textContent = label;
    }
  }

  async function readResponse(response) {
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();

    if (contentType.includes('application/json') && raw) {
      try {
        return JSON.parse(raw);
      } catch (_error) {
        // Fall through to the safe error object below.
      }
    }

    return {
      detail: response.ok
        ? 'The agent returned an unreadable response.'
        : `The agent server failed with HTTP ${response.status}. Please check the deployment logs.`,
      raw,
    };
  }

  async function stopAgent() {
    if (!controller) return;
    controller.abort();
    controller = null;
    setBusy(false, 'stopped');
    addMessage('I stopped the request. You can continue the conversation whenever you are ready.');
    objectiveInput.focus();
  }

  stopButton.addEventListener('click', stopAgent);

  async function sendMessage() {
    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    const normalized = objective.toLowerCase().replace(/[.!?]+$/, '').trim();

    if (!objective) {
      objectiveInput.focus();
      return;
    }

    addMessage(objective, 'user');
    objectiveInput.value = '';
    objectiveInput.style.height = '';

    if (greetingWords.has(normalized)) {
      addMessage(`Hi ${developerName()}. What do you want to create today?`);
      objectiveInput.focus();
      return;
    }

    controller = new AbortController();
    setBusy(true, 'working');
    const pending = addMessage('Amosclaud is working on your request…', 'pending');

    try {
      const response = await fetch('/api/v1/agent/run', {
        method: 'POST',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode,
          objective,
          branch: 'main',
          metadata: { branch: 'main' },
        }),
      });

      const data = await readResponse(response);
      if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

      pending.remove();
      addMessage(data.reply || 'The Agent finished processing your request.');
      setBusy(false, 'ready');
    } catch (error) {
      pending.remove();
      if (error.name !== 'AbortError') {
        addMessage(`I could not finish this request: ${error.message}`);
        setBusy(false, 'error');
      }
    } finally {
      controller = null;
      objectiveInput.focus();
    }
  }

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
