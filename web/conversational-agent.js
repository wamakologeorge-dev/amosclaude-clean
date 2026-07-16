(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  if (!runButton || !objectiveInput || !replies) return;

  const storageKey = 'amosclaud-conversational-agent-v2';
  const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
  const conversation = Array.isArray(saved.conversation) ? saved.conversation : [];
  const intake = saved.intake && typeof saved.intake === 'object' ? saved.intake : {};
  let controller = null;

  const confirmationPhrases = new Set([
    'proceed', 'start', 'start now', 'do it', 'build it', 'fix it', 'make it',
    'deploy it', 'continue', 'go ahead', 'yes proceed', 'yes start', 'execute',
  ]);

  function publish(name, detail = {}) {
    window.dispatchEvent(new CustomEvent(`amosclaud:${name}`, { detail }));
  }

  function normalise(value) {
    return String(value || '').trim().toLowerCase().replace(/[.!?]+$/, '').replace(/\s+/g, ' ');
  }

  function saveState() {
    sessionStorage.setItem(storageKey, JSON.stringify({ conversation: conversation.slice(-20), intake }));
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

  function identifyIntent(text) {
    const value = normalise(text);
    if (/\b(deploy|release|publish)\b/.test(value)) return 'deploy';
    if (/\b(monitor|watch|track)\b/.test(value)) return 'monitor';
    if (/\b(fix|repair|broken|problem|error|bug)\b/.test(value)) return 'fix';
    if (/\b(create|build|make|develop)\b/.test(value)) return 'create';
    return intake.intent || 'create';
  }

  function recordAnswer(text) {
    if (!intake.intent) { intake.intent = identifyIntent(text); intake.request = text; return; }
    if (!intake.outcome) { intake.outcome = text; return; }
    if (!intake.users) { intake.users = text; return; }
    if (!intake.workflow) { intake.workflow = text; return; }
    if (!intake.success) intake.success = text;
  }

  function nextQuestion() {
    if (!intake.outcome) {
      if (intake.intent === 'fix') return 'I understand. What exactly is going wrong, and what should happen instead?';
      if (intake.intent === 'deploy') return 'I understand. What project should be deployed, and where should it go?';
      if (intake.intent === 'monitor') return 'I understand. What system should I monitor, and what change should I report?';
      return 'I understand. What exactly would you like me to create?';
    }
    if (!intake.users) return 'Who will use it or benefit from it?';
    if (!intake.workflow) return 'What is the first important thing the user should be able to do?';
    if (!intake.success) return 'What must be true before I can honestly report that the job is complete?';
    return null;
  }

  function agreedBrief() {
    return [
      `Requested work: ${intake.request || intake.intent || 'engineering task'}`,
      `Outcome: ${intake.outcome || ''}`,
      `Users: ${intake.users || ''}`,
      `First workflow: ${intake.workflow || ''}`,
      `Success condition: ${intake.success || ''}`,
    ].filter(line => !line.endsWith(': ')).join('\n');
  }

  function confirmationReply() {
    return `Thank you. Here is the brief I understood:\n\n${agreedBrief()}\n\nReply “Proceed” when you want me to start the real job.`;
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
      ['Understand', 'I’m understanding the agreed brief and preparing the real job…'],
      ['Inspect', 'I’m inspecting the real project evidence now…'],
      ['Act', 'I’m executing the authorized job and recording real progress…'],
      ['Verify', 'I’m testing and verifying the actual result…'],
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

  async function executeConfirmedJob(raw, presence) {
    const response = await fetch('/api/v1/agent/run', {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: intake.intent === 'deploy' ? 'deploy' : intake.intent === 'monitor' ? 'monitor' : 'fix',
        objective: raw,
        branch: 'main',
        metadata: {
          branch: 'main', conversation: conversation.slice(-12), previous_objective: agreedBrief(),
          conversation_first: true, user_confirmed_execution: true,
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

    const confirmed = confirmationPhrases.has(normalise(raw)) && Boolean(intake.success);
    controller = new AbortController();
    setStatus(confirmed ? 'executing' : 'writing', true);
    const presence = addPresence(
      confirmed ? 'Thank you. I’m starting the real job now…' : 'I’m reading your answer carefully…',
      confirmed ? 'executing' : 'writing',
    );

    if (confirmed) publish('agent-start', { objective: agreedBrief(), mode: intake.intent || 'fix' });

    try {
      if (!confirmed) {
        recordAnswer(raw);
        const question = nextQuestion();
        presence.remove();
        const reply = question || confirmationReply();
        addMessage(reply, 'agent');
        remember('assistant', reply);
        setStatus('ready');
        return;
      }

      const data = await executeConfirmedJob(raw, presence);
      presence.remove();
      const reply = data.copilot_reply || data.reply || data.message;
      if (!reply) throw new Error('The live runtime returned no result message.');
      addMessage(reply, 'agent');
      remember('assistant', reply);
      publish('agent-phase', { index: 4, phase: 'Verify', state: 'complete', note: 'Verification finished and evidence was recorded.' });
      publish('agent-result', data);
      setStatus(String(data.status || '').toLowerCase() === 'failed' ? 'error' : 'ready');
    } catch (error) {
      presence.remove();
      const message = error.name === 'AbortError'
        ? 'I stopped the job. We can continue calmly from the same brief when you are ready.'
        : `I’m sorry, the live job could not finish: ${error.message}`;
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