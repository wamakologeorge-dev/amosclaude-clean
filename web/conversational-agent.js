(() => {
  const runButton = document.getElementById('btn-run-agent');
  const objectiveInput = document.getElementById('agent-objective-input');
  const replies = document.getElementById('agent-replies');
  const statusBadge = document.getElementById('agent-status');
  if (!runButton || !objectiveInput || !replies) return;

  const storageKey = 'amosclaud-conversational-agent-v4';
  const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
  const conversation = Array.isArray(saved.conversation) ? saved.conversation : [];
  let bundleDraft = saved.bundleDraft && typeof saved.bundleDraft === 'object' ? saved.bundleDraft : null;
  let latestBundleResult = saved.latestBundleResult && typeof saved.latestBundleResult === 'object'
    ? saved.latestBundleResult : null;
  let controller = null;

  const confirmationPhrases = new Set([
    'proceed', 'proceed with the plan', 'start', 'start now', 'do it', 'build it',
    'create it', 'make it', 'continue', 'go ahead', 'yes proceed', 'yes start', 'execute',
  ]);
  const resultPhrases = /\b(show|open|give|bring|display|see)\b.*\b(result|results|evidence|bundle)\b|\bwhat (did|was) (you|autonomous) (create|build|make)\b/i;
  const bundleTypePatterns = [
    ['deployment', /\b(deployment|deployable|release package)\b/i],
    ['connector', /\b(connector|mcp|integration package)\b/i],
    ['extension', /\b(extension|plugin|add-on)\b/i],
    ['runtime', /\b(runtime|executable runtime)\b/i],
    ['source', /\b(source|source code|code bundle)\b/i],
  ];

  function publish(name, detail = {}) {
    window.dispatchEvent(new CustomEvent(`amosclaud:${name}`, { detail }));
  }

  function normalise(value) {
    return String(value || '').trim().toLowerCase().replace(/[.!?]+$/, '').replace(/\s+/g, ' ');
  }

  function saveState() {
    sessionStorage.setItem(storageKey, JSON.stringify({
      conversation: conversation.slice(-20), bundleDraft, latestBundleResult,
    }));
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

  function slug(value) {
    return String(value || '')
      .toLowerCase().replace(/\b(type|bundle|package|create|build|make|a|an|the)\b/g, ' ')
      .replace(/[^a-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
  }

  function detectBundleType(text) {
    for (const [type, pattern] of bundleTypePatterns) if (pattern.test(text)) return type;
    return null;
  }

  function beginBundleDraft(text) {
    const type = detectBundleType(text);
    const mentionsBundle = /\b(bundle|package|source|runtime|connector|deployment|extension)\b/i.test(text);
    if (!type && !mentionsBundle) return false;
    const withoutType = bundleTypePatterns.reduce((value, [, pattern]) => value.replace(pattern, ' '), text);
    const derivedName = slug(withoutType) || slug(text);
    bundleDraft = {
      name: derivedName || '',
      version: '0.1.0',
      bundle_type: type || '',
      source_path: null,
      description: String(text).trim(),
      entrypoint: null,
      confirmed: false,
    };
    saveState();
    return true;
  }

  function bundleReady() {
    return Boolean(bundleDraft?.name && bundleDraft?.bundle_type &&
      (bundleDraft.bundle_type !== 'deployment' || bundleDraft.entrypoint));
  }

  function bundleQuestion() {
    if (!bundleDraft.bundle_type) return 'Which real bundle should I create: Source, Runtime, Connector, Deployment, or Extension?';
    if (!bundleDraft.name) return 'What name should the bundle use?';
    if (bundleDraft.bundle_type === 'deployment' && !bundleDraft.entrypoint) {
      return 'What exact entrypoint should the deployment bundle start, for example “python app.py” or “uvicorn app:app”?';
    }
    return null;
  }

  function updateBundleDraft(text) {
    const type = detectBundleType(text);
    if (type && !bundleDraft.bundle_type) bundleDraft.bundle_type = type;
    else if (!bundleDraft.name) bundleDraft.name = slug(text);
    else if (bundleDraft.bundle_type === 'deployment' && !bundleDraft.entrypoint) bundleDraft.entrypoint = text.trim();
    saveState();
  }

  function bundleBrief() {
    const rows = [
      `Name: ${bundleDraft.name}`,
      `Type: ${bundleDraft.bundle_type}`,
      `Version: ${bundleDraft.version}`,
      `Source: ${bundleDraft.source_path || 'authenticated Amosclaud workspace'}`,
    ];
    if (bundleDraft.entrypoint) rows.push(`Entrypoint: ${bundleDraft.entrypoint}`);
    rows.push(`Description: ${bundleDraft.description}`);
    return rows.join('\n');
  }

  async function readJson(response) {
    const raw = await response.text();
    let data = {};
    try { data = raw ? JSON.parse(raw) : {}; } catch { data = { detail: raw || 'Invalid server response' }; }
    if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
    return data;
  }

  async function createRealBundle(presence) {
    publish('agent-start', { objective: `Create ${bundleDraft.bundle_type} bundle ${bundleDraft.name}`, mode: 'create' });
    publish('agent-phase', { index: 0, phase: 'Understand', state: 'complete', note: 'The confirmed bundle brief is complete.' });
    presence.textContent = 'Autonomous is validating the real workspace source…';
    publish('agent-phase', { index: 1, phase: 'Validate source', state: 'active', note: 'Validating the authenticated workspace and bundle fields.' });

    const response = await fetch('/api/v1/bundles', {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(bundleDraft),
    });
    const created = await readJson(response);
    const manifest = created.bundle || {};
    const result = {
      status: 'success',
      kind: 'bundle',
      reply: `Created the real ${manifest.bundle_type} bundle “${manifest.name}” and verified its archive manifest.`,
      message: 'Bundle created by Amosclaud Autonomous.',
      bundle: manifest,
      archive_size: created.archive_size,
      download_url: created.download_url,
      changed_files: Array.isArray(manifest.files) ? manifest.files.map(item => item.path) : [],
      checks: [
        { name: 'source-validation', status: 'passed', summary: `${manifest.files?.length || 0} safe file(s) included` },
        { name: 'archive-integrity', status: manifest.archive_sha256 ? 'passed' : 'failed', summary: manifest.archive_sha256 || 'No archive checksum returned' },
      ],
      logs: [
        `Bundle ID: ${manifest.bundle_id}`,
        `Format: ${manifest.format}`,
        `Archive bytes: ${created.archive_size}`,
        `Archive SHA-256: ${manifest.archive_sha256}`,
      ],
    };
    latestBundleResult = result;
    bundleDraft = null;
    saveState();
    publish('agent-phase', { index: 3, phase: 'Verify', state: 'complete', note: 'The real manifest, file list, size, and SHA-256 evidence were returned.' });
    publish('agent-result', result);
    return result;
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
    return conversation.filter(item => item.role === 'user').map(item => item.content).filter(Boolean).join('\n');
  }

  function flattenPipeline(pipeline, initial) {
    const jobs = Array.isArray(pipeline.jobs) ? pipeline.jobs : [];
    const logs = jobs.flatMap(job => Array.isArray(job.logs) ? job.logs : []);
    return { ...initial, ...pipeline, pipeline_id: pipeline.id || initial.pipeline_id,
      reply: pipeline.copilot_reply || pipeline.message || initial.reply, jobs, logs,
      checks: Array.isArray(pipeline.checks) ? pipeline.checks : (initial.checks || []) };
  }

  async function pollPipeline(initial, presence) {
    let latest = initial;
    for (let attempt = 0; attempt < 180; attempt += 1) {
      if (['success', 'failed', 'cancelled'].includes(String(latest.status || '').toLowerCase())) return latest;
      await new Promise(resolve => setTimeout(resolve, 1000));
      const response = await fetch(`/api/v1/pipelines/${encodeURIComponent(initial.pipeline_id)}`, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      latest = flattenPipeline(await readJson(response), initial);
      presence.textContent = 'Autonomous is executing and verifying the real job…';
    }
    throw new Error('The live job is still running. Its saved pipeline remains available for another status check.');
  }

  async function askAutonomous(raw, confirmed, presence) {
    const response = await fetch('/api/v1/agent/run', {
      method: 'POST', credentials: 'same-origin', signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        mode: confirmed ? identifyIntent(raw) : 'autonomous-check', objective: raw, branch: 'main',
        metadata: { branch: 'main', conversation: conversation.slice(-12), previous_objective: agreedContext(),
          conversation_first: true, user_confirmed_execution: confirmed, single_visible_agent: true },
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
    const confirmed = confirmationPhrases.has(normalise(raw));

    if (resultPhrases.test(raw) && latestBundleResult) {
      addMessage(latestBundleResult.reply, 'agent');
      publish('agent-result', latestBundleResult);
      setStatus('ready');
      return;
    }

    if (!bundleDraft) beginBundleDraft(raw);
    else if (!confirmed) updateBundleDraft(raw);

    if (bundleDraft && !confirmed) {
      const question = bundleQuestion();
      const reply = question || `I have the real bundle brief:\n\n${bundleBrief()}\n\nReply “Proceed with the plan” and I will create it through the authenticated Bundles API.`;
      addMessage(reply, 'agent');
      remember('assistant', reply);
      setStatus('ready');
      return;
    }

    controller = new AbortController();
    setStatus(confirmed ? 'executing' : 'writing', true);
    const presence = addPresence(confirmed ? 'Autonomous is starting the confirmed real job…' : 'Amosclaud Autonomous is understanding your message…', confirmed ? 'executing' : 'writing');

    try {
      let data;
      if (confirmed && bundleDraft) {
        if (!bundleReady()) throw new Error(bundleQuestion() || 'The bundle brief is incomplete.');
        data = await createRealBundle(presence);
      } else {
        data = await askAutonomous(raw, confirmed, presence);
      }
      presence.remove();
      const reply = data.copilot_reply || data.reply || data.message;
      if (!reply) throw new Error('The Autonomous runtime returned no response.');
      addMessage(reply, 'agent');
      remember('assistant', reply);
      if (!String(data.pipeline_id || '').startsWith('conversation-') && data.kind !== 'bundle') publish('agent-result', data);
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