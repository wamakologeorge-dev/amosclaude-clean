(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  if (!runButton || !objectiveInput || !replies) return;

  const storageKey = 'amosclaud-conversational-agent-v3';
  const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
  const conversation = Array.isArray(saved.conversation) ? saved.conversation : [];
  let controller = null;

  const confirmationPhrases = new Set([
    'proceed', 'start', 'start now', 'do it', 'build it', 'fix it', 'make it',
    'deploy it', 'continue', 'go ahead', 'yes proceed', 'yes start', 'execute',
  ]);
  const shortAffirmations = new Set(['yes', 'yes please', 'okay', 'ok', 'sure']);

  function publish(name, detail = {}) {
    window.dispatchEvent(new CustomEvent(`amosclaud:${name}`, { detail }));
  }

  function normalise(value) {
    return String(value || '').trim().toLowerCase().replace(/[.!?]+$/, '').replace(/\s+/g, ' ');
  }

  function saveState() {
    sessionStorage.setItem(storageKey, JSON.stringify({ conversation: conversation.slice(-20) }));
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

  function lastAssistantMessage() {
    return [...conversation].reverse().find(item => item.role === 'assistant')?.content || '';
  }

  function isExecutionConfirmation(text) {
    const value = normalise(text);
    if (confirmationPhrases.has(value)) return true;
    if (!shortAffirmations.has(value)) return false;
    return /\b(edit|change|fix|build|create|deploy|execute|start|apply|repository|verify)\b/i.test(lastAssistantMessage());
  }

  function executionObjective(text, confirmed) {
    return confirmed && shortAffirmations.has(normalise(text)) ? 'proceed' : text;
  }

  function identifyIntent(text) {
    const context = `${conversation.map(item => item.content).join(' ')} ${text}`.toLowerCase();
    if (/\b(deploy|release|publish)\b/.test(context)) return 'deploy';
    if (/\b(monitor|watch|track)\b/.test(context)) return 'monitor';
    if (/\b(fix|repair|broken|problem|error|bug)\b/.test(context)) return 'fix';
    if (/\b(create|build|make|develop|website|application|app)\b/.test(context)) return 'build';
    return 'autonomous-check';
  }

  function agreedContext() {
    return conversation
      .filter(item => item.role === 'user')
      .map(item => item.content)
      .filter(Boolean)
      .join('\n');
  }

  async function readJson(response) {
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw || 'Invalid server response' }; }
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  function flattenPipeline(pipeline, initial) {
    const jobs = Array.isArray(pipeline.jobs) ? pipeline.jobs : [];
    const logs = jobs.flatMap(job => Array.isArray(job.logs) ? job.logs : []);
    return {
      ...initial,
      ...pipeline,
      pipeline_id: pipeline.id || initial.pipeline_id,
      reply: pipeline.copilot_reply || pipeline.message || initial.reply,
      jobs,
      logs,
      checks: Array.isArray(pipeline.checks) ? pipeline.checks : (initial.checks || []),
    };
  }

  async function pollPipeline(initial, presence) {
    let latest = initial;
    let lastPhase = -1;
    const phases = [
      ['Understand', 'I’m understanding the agreed request and preparing the real job…'],
      ['Inspect', 'Autonomous is inspecting the real project evidence now…'],
      ['Act', 'Autonomous and its internal workers are executing the authorized job…'],
      ['Verify', 'Autonomous is testing and verifying the actual result…'],
    ];
    for (let attempt = 0; attempt < 180; attempt += 1) {
      const currentStatus = String(latest.status || '').toLowerCase();
      if (['success', 'failed', 'cancelled'].includes(currentStatus)) return latest;
      const phase = Math.min(Math.floor(attempt / 8), phases.length - 1);
      presence.textContent = phases[phase][1];
      if (phase !== lastPhase) {
        publish('agent-phase', { index: phase, phase: phases[phase][0], state: 'active', note: phases[phase][1] });
        lastPhase = phase;
      }
      await new Promise(resolve => setTimeout(resolve, 1000));
      const response = await fetch(`/api/v1/pipelines/${encodeURIComponent(initial.pipeline_id)}`, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      latest = flattenPipeline(await readJson(response), initial);
    }
    throw new Error('The live job is still running. Its saved pipeline remains available for another status check.');
  }

  async function askAutonomous(raw, confirmed, presence) {
    const mode = confirmed ? identifyIntent(raw) : 'autonomous-check';
    const response = await fetch('/api/v1/agent/run', {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode,
        objective: executionObjective(raw, confirmed),
        branch: 'main',
        metadata: {
          branch: 'main',
          conversation: conversation.slice(-12),
          previous_objective: agreedContext(),
          conversation_first: true,
          user_confirmed_execution: confirmed,
          single_visible_agent: true,
        },
      }),
    });
    let data = await readJson(response);
    if (!String(data.pipeline_id || '').startsWith('conversation-')) data = await pollPipeline(data, presence);
    return data;
  }

  async function sendMessage() {
    const raw = objectiveInput.value.trim();
    if (!raw || controller) return;
    addMessage(raw, 'user');
    remember('user', raw);
    objectiveInput.value = '';
    objectiveInput.style.height = '';

    const confirmed = isExecutionConfirmation(raw);
    controller = new AbortController();
    setStatus(confirmed ? 'executing' : 'writing', true);
    const presence = addPresence(
      confirmed ? 'Thank you. Autonomous is starting the real job now…' : 'Amosclaud Autonomous is understanding your message…',
      confirmed ? 'executing' : 'writing',
    );

    if (confirmed) publish('agent-start', { objective: agreedContext(), mode: identifyIntent(raw) });

    try {
      const data = await askAutonomous(raw, confirmed, presence);
      presence.remove();
      const reply = data.copilot_reply || data.reply || data.message;
      if (!reply) throw new Error('The Autonomous runtime returned no response.');
      addMessage(reply, 'agent');
      remember('assistant', reply);
      if (!String(data.pipeline_id || '').startsWith('conversation-')) {
        publish('agent-phase', { index: 4, phase: 'Verify', state: 'complete', note: 'Verification finished and evidence was recorded.' });
        publish('agent-result', data);
      }
      setStatus(String(data.status || '').toLowerCase() === 'failed' ? 'error' : 'ready');
    } catch (error) {
      presence.remove();
      const message = error.name === 'AbortError'
        ? 'I stopped the job. We can continue from the same conversation when you are ready.'
        : `I’m sorry, Autonomous could not complete this request: ${error.message}`;
      addMessage(message, 'agent', error.name === 'AbortError' ? '' : 'agent-error');
      if (confirmed) publish('agent-error', { message });
      setStatus(error.name === 'AbortError' ? 'ready' : 'error');
    } finally {
      controller = null;
      saveState();
      objectiveInput.focus();
    }
  }

  document.querySelectorAll('[data-agent-suggestion]').forEach(button => {
    button.addEventListener('click', () => { objectiveInput.value = button.dataset.agentSuggestion || ''; objectiveInput.focus(); });
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
