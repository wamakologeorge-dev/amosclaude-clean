(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const output = document.getElementById('ws-output');
  const state = document.getElementById('ws-run-state');
  const branchSelect = document.getElementById('ws-branch');
  const chatInput = document.getElementById('ws-chat-input');
  const chatSend = document.getElementById('ws-chat-send');
  let repository = null;
  let busy = false;

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
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
    state.textContent = normalized === 'pending' ? 'Queued' : normalized.charAt(0).toUpperCase() + normalized.slice(1);
    state.className = `ws-run-state ${normalized === 'pending' ? 'running' : normalized}`;
  }

  function addMessage(text, role = 'agent') {
    const message = document.createElement('div');
    message.className = `ws-chat-message ${role}`;
    message.textContent = String(text || '');
    output.appendChild(message);
    output.scrollTop = output.scrollHeight;
    return message;
  }

  function formatPipeline(result, label) {
    const lines = [];
    const reply = result.copilot_reply || result.reply || result.message;
    if (reply) lines.push(reply);
    const jobs = result.jobs || [];
    jobs.forEach(job => {
      lines.push(`${job.name || 'Autonomous task'} — ${String(job.status || 'unknown').toUpperCase()}`);
      (job.logs || []).forEach(log => lines.push(`• ${log}`));
    });
    (result.checks || []).forEach(check => {
      lines.push(`• ${check.name}: ${check.status}${check.summary ? ` — ${check.summary}` : ''}`);
    });
    if (!lines.length) lines.push(`${label}: ${String(result.status || 'unknown').toUpperCase()}`);
    return lines.join('\n');
  }

  async function waitForPipeline(pipelineId, label, liveMessage) {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const pipeline = await api(`/api/v1/pipelines/${encodeURIComponent(pipelineId)}`);
      setRunState(pipeline.status);
      liveMessage.textContent = formatPipeline(pipeline, label);
      output.scrollTop = output.scrollHeight;
      if (['success', 'failed', 'cancelled'].includes(String(pipeline.status).toLowerCase())) return pipeline;
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error('Autonomous did not finish within 10 minutes. The task may still be running in the background.');
  }

  function selectMode(command) {
    const text = command.toLowerCase();
    if (/\b(deploy|release|publish)\b/.test(text)) return 'deploy';
    if (/\b(fix|repair|change|edit|remove|delete|build|create|make)\b/.test(text)) return 'fix';
    if (/\b(monitor|watch|track)\b/.test(text)) return 'monitor';
    return 'autonomous-check';
  }

  async function runCommand(command, forcedMode = null, label = 'Autonomous') {
    const objective = String(command || '').trim();
    if (!objective || busy) return;
    busy = true;
    addMessage(objective, 'user');
    if (chatInput) chatInput.value = '';
    setRunState('running');
    const liveMessage = addMessage(`I am inspecting ${repository?.name || 'this repository'} on ${branch()} now…`, 'agent');
    try {
      const result = await api('/api/v1/agent/run', {
        method: 'POST',
        body: JSON.stringify({
          mode: forcedMode || selectMode(objective),
          objective,
          branch: branch(),
          metadata: {
            repository_id: Number(repositoryId),
            repository_name: repository.name,
            use_agent: true,
            apply_changes: true,
            source: 'repository-autonomous-chat',
            user_confirmed_execution: true,
          },
        }),
      });
      setRunState(result.status);
      liveMessage.textContent = formatPipeline(result, label);
      if (result.pipeline_id && ['pending', 'running'].includes(String(result.status).toLowerCase())) {
        await waitForPipeline(result.pipeline_id, label, liveMessage);
      }
    } catch (error) {
      setRunState('failed');
      liveMessage.textContent = `I could not finish that command. Exact problem: ${error.message}`;
    } finally {
      busy = false;
      chatInput?.focus();
    }
  }

  function replaceHandler(id, mode, command) {
    const oldButton = document.getElementById(id);
    if (!oldButton) return;
    const button = oldButton.cloneNode(true);
    oldButton.replaceWith(button);
    button.addEventListener('click', () => runCommand(command(repository), mode, button.textContent.trim()));
  }

  chatSend?.addEventListener('click', () => runCommand(chatInput?.value));
  chatInput?.addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      runCommand(chatInput.value);
    }
  });

  (async () => {
    try {
      repository = await api(`/api/v1/repositories/${repositoryId}`);
      localStorage.setItem('amosclaud-last-repository-id', String(repositoryId));
      localStorage.setItem('amosclaud-last-repository-name', `${repository.owner_name}/${repository.name}`);
      replaceHandler('ws-build', 'build', repo => `Build repository ${repo.name} on branch ${branch()}, make the required changes, test them, and report verified evidence.`);
      replaceHandler('ws-test', 'autonomous-check', repo => `Run the repository tests for ${repo.name} on branch ${branch()} and report the exact results.`);
      replaceHandler('ws-review', 'autonomous-check', repo => `Review repository ${repo.name} on branch ${branch()}, identify real problems, and report evidence.`);
      replaceHandler('ws-deploy', 'deploy', repo => `Prepare repository ${repo.name} on branch ${branch()} for deployment and report every blocker and verified result.`);
    } catch (error) {
      setRunState('failed');
      addMessage(`Workspace setup failed: ${error.message}`, 'agent');
    }
  })();
})();
