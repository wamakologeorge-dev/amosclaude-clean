(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const modeInput = document.getElementById('agent-mode-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  if (!runButton || !objectiveInput || !modeInput || !replies) return;

  const storageKey = 'amosclaud-conversational-agent';
  const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
  const conversation = Array.isArray(saved.conversation) ? saved.conversation : [];
  let agreedBrief = String(saved.agreedBrief || '');
  let controller = null;

  const confirmationPhrases = new Set([
    'proceed', 'start', 'start now', 'do it', 'build it', 'fix it', 'make it',
    'deploy it', 'continue', 'go ahead', 'yes proceed', 'yes start', 'execute',
  ]);

  function normalise(value) {
    return String(value || '').trim().toLowerCase().replace(/[.!?]+$/, '').replace(/\s+/g, ' ');
  }

  function saveState() {
    sessionStorage.setItem(storageKey, JSON.stringify({ conversation: conversation.slice(-20), agreedBrief }));
  }

  function addMessage(text, role = 'agent', className = '') {
    replies.querySelector('.agent-reply.muted')?.remove();
    const item = document.createElement('div');
    item.className = `agent-reply chat-message chat-message-${role} ${className}`.trim();
    item.textContent = String(text || '');
    replies.appendChild(item);
    replies.scrollTop = replies.scrollHeight;
    return item;
  }

  function addPresence(text, state = 'writing') {
    const item = addMessage(text, 'agent', `agent-presence agent-presence-${state}`);
    item.setAttribute('aria-live', 'polite');
    return item;
  }

  function setStatus(label, busy = false) {
    runButton.disabled = busy;
    if (!statusBadge) return;
    statusBadge.textContent = label;
    statusBadge.className = `badge ${busy ? 'badge-running' : label === 'error' ? 'badge-failed' : 'badge-success'}`;
  }

  function remember(role, content) {
    conversation.push({ role, content: String(content).slice(0, 4000) });
    if (conversation.length > 20) conversation.splice(0, conversation.length - 20);
    saveState();
  }

  async function readJson(response) {
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw || 'Invalid response' }; }
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  async function pollPipeline(initial, presence) {
    let latest = initial;
    for (let attempt = 0; attempt < 180; attempt += 1) {
      const status = String(latest.status || '').toLowerCase();
      if (['success', 'failed', 'cancelled'].includes(status)) return latest;
      const messages = [
        'I’m inspecting the project and understanding the safest next action…',
        'I’m writing and applying the authorized changes now…',
        'The job is running. I’m testing and verifying the result…',
      ];
      presence.textContent = messages[Math.min(Math.floor(attempt / 8), messages.length - 1)];
      await new Promise(resolve => setTimeout(resolve, 1000));
      const response = await fetch(`/api/v1/pipelines/${encodeURIComponent(initial.pipeline_id)}`, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      latest = await readJson(response);
    }
    throw new Error('The job is still running. Its saved pipeline can be checked again shortly.');
  }

  async function sendMessage() {
    const raw = objectiveInput.value.trim();
    if (!raw || controller) return;

    addMessage(raw, 'user');
    remember('user', raw);
    objectiveInput.value = '';
    objectiveInput.style.height = '';

    const confirmation = confirmationPhrases.has(normalise(raw));
    if (!confirmation) agreedBrief = [...conversation.filter(item => item.role === 'user').map(item => item.content)].join(' → ');
    saveState();

    controller = new AbortController();
    setStatus(confirmation ? 'executing' : 'writing', true);
    const presence = addPresence(
      confirmation
        ? 'Thank you. I understand. I’m starting the job now…'
        : 'I’m reading that carefully and preparing my next question…',
      confirmation ? 'executing' : 'writing',
    );

    try {
      const objective = confirmation
        ? raw
        : `Help me discuss and clarify this request before any execution. Ask one calm follow-up question: ${raw}`;
      const response = await fetch('/api/v1/agent/run', {
        method: 'POST',
        credentials: 'same-origin',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: confirmation ? 'fix' : 'autonomous-check',
          objective,
          branch: 'main',
          metadata: {
            branch: 'main',
            conversation: conversation.slice(-12),
            previous_objective: agreedBrief,
            conversation_first: true,
            user_confirmed_execution: confirmation,
          },
        }),
      });
      let data = await readJson(response);
      const conversational = String(data.pipeline_id || '').startsWith('conversation-');
      if (!conversational) data = await pollPipeline(data, presence);

      presence.remove();
      const reply = data.copilot_reply || data.reply || data.message || 'I finished the requested work.';
      addMessage(reply, 'agent');
      remember('assistant', reply);
      setStatus(String(data.status || 'ready').toLowerCase() === 'failed' ? 'error' : 'ready');
    } catch (error) {
      presence.remove();
      addMessage(
        error.name === 'AbortError'
          ? 'I stopped the job. We can continue the conversation whenever you are ready.'
          : `I’m sorry, I could not finish that yet: ${error.message}`,
        'agent', 'agent-error',
      );
      setStatus(error.name === 'AbortError' ? 'ready' : 'error');
    } finally {
      controller = null;
      objectiveInput.focus();
    }
  }

  document.querySelectorAll('[data-agent-suggestion]').forEach(button => {
    button.addEventListener('click', () => {
      objectiveInput.value = button.dataset.agentSuggestion || '';
      objectiveInput.focus();
    });
  });
  runButton.addEventListener('click', event => { event.preventDefault(); sendMessage(); });
  objectiveInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); sendMessage(); }
  });
  objectiveInput.addEventListener('input', () => {
    objectiveInput.style.height = 'auto';
    objectiveInput.style.height = `${Math.min(objectiveInput.scrollHeight, 180)}px`;
  });
})();
