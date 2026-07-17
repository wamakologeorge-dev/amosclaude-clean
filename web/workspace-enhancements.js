(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const output = document.getElementById('ws-output');
  const state = document.getElementById('ws-run-state');
  const branchSelect = document.getElementById('ws-branch');
  const form = document.getElementById('ws-agent-command-form');
  const commandInput = document.getElementById('ws-agent-command');
  const runButton = document.getElementById('ws-agent-run');
  const thread = document.getElementById('ws-agent-thread');
  const target = document.getElementById('ws-agent-target');
  if (!output || !state || !form || !commandInput || !runButton || !thread) return;

  let repository = null;
  let active = false;
  const conversation = [];

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
    });
    const contentType = response.headers.get('content-type') || '';
    const raw = await response.text();
    let data = null;
    if (raw) {
      if (contentType.includes('application/json')) {
        try { data = JSON.parse(raw); } catch { data = { detail: 'The server returned invalid JSON.' }; }
      } else {
        data = { detail: raw.trim() || `Request failed (${response.status})` };
      }
    }
    if (!response.ok) throw new Error(data?.detail || data?.message || `Request failed (${response.status})`);
    return data;
  }

  const branch = () => branchSelect?.value || repository?.default_branch || 'main';

  function setRunState(value) {
    const normalized = String(value || 'ready').toLowerCase();
    const labels = { pending: 'Queued', running: 'Operating', success: 'Success', failed: 'Blocked', cancelled: 'Stopped', ready: 'Ready' };
    state.textContent = labels[normalized] || normalized.charAt(0).toUpperCase() + normalized.slice(1);
    state.className = `ws-run-state ${normalized === 'pending' ? 'running' : normalized}`;
  }

  function addMessage(role, text) {
    const article = document.createElement('article');
    article.className = `ws-agent-message ws-agent-message-${role}`;
    const label = document.createElement('strong');
    label.textContent = role === 'user' ? 'You' : 'Autonomous';
    const body = document.createElement('p');
    body.textContent = String(text || '');
    article.append(label, body);
    thread.appendChild(article);
    thread.scrollTop = thread.scrollHeight;
    conversation.push({ role: role === 'user' ? 'user' : 'assistant', content: String(text || '').slice(0, 4000) });
    if (conversation.length > 16) conversation.splice(0, conversation.length - 16);
  }

  function chooseMode(command) {
    const text = String(command || '').toLowerCase();
    if (/\b(deploy|release|publish|production)\b/.test(text)) return 'deploy';
    if (/\b(monitor|watch|track|observe)\b/.test(text)) return 'monitor';
    if (/\b(fix|repair|change|edit|remove|delete|create|build|implement|add)\b/.test(text)) return 'fix';
    return 'autonomous-check';
  }

  function formatPipeline(result) {
    const lines = [];
    const reply = result.copilot_reply || result.reply || result.message;
    if (reply) lines.push(reply);
    (result.jobs || []).forEach(job => {
      lines.push('', `${job.name || 'Autonomous operation'} — ${String(job.status || 'unknown').toUpperCase()}`);
      (job.logs || []).forEach(log => lines.push(`• ${log}`));
    });
    (result.checks || []).forEach(check => {
      lines.push(`• ${check.name}: ${check.status}${check.summary ? ` — ${check.summary}` : ''}`);
    });
    (result.logs || []).forEach(log => {
      const line = `• ${log}`;
      if (!lines.includes(line)) lines.push(line);
    });
    if (result.started_at) lines.push('', `Started: ${new Date(result.started_at).toLocaleString()}`);
    if (result.finished_at) lines.push(`Finished: ${new Date(result.finished_at).toLocaleString()}`);
    return lines.join('\n').trim() || 'Autonomous returned no displayable evidence.';
  }

  async function waitForPipeline(initial) {
    let latest = initial;
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const status = String(latest.status || '').toLowerCase();
      setRunState(status);
      output.textContent = formatPipeline(latest);
      if (['success', 'failed', 'cancelled'].includes(status)) return latest;
      await new Promise(resolve => setTimeout(resolve, 2000));
      latest = await api(`/api/v1/pipelines/${encodeURIComponent(initial.pipeline_id)}`);
    }
    throw new Error('The operation is still running after 10 minutes. Its saved pipeline remains available.');
  }

  async function operate(command) {
    if (active) return;
    active = true;
    runButton.disabled = true;
    commandInput.disabled = true;
    setRunState('running');
    addMessage('user', command);
    addMessage('agent', `Command received. I am operating on ${repository.name}/${branch()} and will return verified evidence.`);
    output.textContent = `Operating on ${repository.name} branch ${branch()}…\n\nInspecting repository evidence and preparing the governed action.`;

    try {
      const result = await api('/api/v1/agent/run', {
        method: 'POST',
        body: JSON.stringify({
          mode: chooseMode(command),
          objective: command,
          branch: branch(),
          metadata: {
            repository_id: Number(repositoryId),
            repository_name: repository.name,
            branch: branch(),
            use_agent: true,
            apply_changes: true,
            user_confirmed_execution: true,
            conversation: conversation.slice(-12),
            source: 'repository-autonomous-system-panel',
            single_visible_agent: true,
          },
        }),
      });
      const finalResult = result.pipeline_id && ['pending', 'running'].includes(String(result.status).toLowerCase())
        ? await waitForPipeline(result)
        : result;
      setRunState(finalResult.status);
      output.textContent = formatPipeline(finalResult);
      const reply = finalResult.copilot_reply || finalResult.reply || finalResult.message || 'Operation completed. Review the verified result below.';
      addMessage('agent', reply);
    } catch (error) {
      setRunState('failed');
      const message = `I stopped safely. Exact problem: ${error.message}`;
      output.textContent = `${message}\n\nNo success is claimed without verified evidence.`;
      addMessage('agent', message);
    } finally {
      active = false;
      runButton.disabled = false;
      commandInput.disabled = false;
      commandInput.value = '';
      commandInput.focus();
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    const command = commandInput.value.trim();
    if (command) operate(command);
  });

  commandInput.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  branchSelect?.addEventListener('change', () => {
    if (target && repository) target.textContent = `Selected target: ${repository.name} / ${branch()}`;
  });

  (async () => {
    try {
      repository = await api(`/api/v1/repositories/${repositoryId}`);
      if (target) target.textContent = `Selected target: ${repository.name} / ${branch()}`;
      setRunState('ready');
    } catch (error) {
      setRunState('failed');
      output.textContent = `Autonomous setup failed: ${error.message}`;
      runButton.disabled = true;
    }
  })();
})();