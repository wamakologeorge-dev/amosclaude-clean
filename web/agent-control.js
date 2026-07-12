(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const modeInput = document.getElementById('agent-mode-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  if (!runButton || !objectiveInput || !modeInput || !replies) return;

  const compose = runButton.closest('.agent-compose');
  const stopButton = document.createElement('button');
  stopButton.id = 'btn-stop-agent';
  stopButton.type = 'button';
  stopButton.className = 'btn-stop-agent';
  stopButton.textContent = 'Stop';
  stopButton.hidden = true;
  compose.appendChild(stopButton);

  let controller = null;
  const greetingWords = new Set(['hi', 'hello', 'hey', 'hiya', 'yo', 'good morning', 'good afternoon', 'good evening']);

  function developerName() {
    const raw = document.getElementById('current-user')?.textContent?.trim() || 'Developer';
    return raw.split(/\s+/)[0] || 'Developer';
  }

  function isNearBottom() {
    return replies.scrollHeight - replies.scrollTop - replies.clientHeight < 96;
  }

  function addMessage(text, role = 'agent') {
    const placeholder = replies.querySelector('.agent-reply.muted');
    if (placeholder) placeholder.remove();

    const shouldFollow = isNearBottom();
    const item = document.createElement('div');
    item.className = `agent-reply chat-message chat-message-${role}`;
    item.textContent = text;
    replies.appendChild(item);

    if (shouldFollow) {
      requestAnimationFrame(() => {
        replies.scrollTop = replies.scrollHeight;
      });
    }
    return item;
  }

  function setBusy(busy, label = 'ready') {
    runButton.disabled = busy;
    stopButton.hidden = !busy;
    if (statusBadge) {
      statusBadge.className = `badge ${busy ? 'badge-running' : 'badge-success'}`;
      statusBadge.textContent = label;
    }
  }

  async function stopAgent() {
    if (!controller) return;
    controller.abort();
    controller = null;
    setBusy(false, 'stopped');
    addMessage('I stopped the request. You can continue the conversation whenever you are ready.');
  }

  stopButton.addEventListener('click', stopAgent);

  async function sendMessage() {
    const objective = objectiveInput.value.trim();
    const mode = modeInput.value;
    const normalized = objective.toLowerCase().replace(/[.!?]+$/, '').trim();

    if (!objective) return;

    addMessage(objective, 'user');
    objectiveInput.value = '';

    if (greetingWords.has(normalized)) {
      addMessage(`Hi ${developerName()}. What do you want to create today?`);
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

      const data = await response.json();
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
})();
