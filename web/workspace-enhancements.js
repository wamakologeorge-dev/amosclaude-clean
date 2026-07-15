(() => {
  const repositoryId = location.pathname.split('/').filter(Boolean).pop();
  const output = document.getElementById('ws-output');
  const state = document.getElementById('ws-run-state');
  const branchSelect = document.getElementById('ws-branch');
  let repository = null;

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
    const normalized = String(value || 'idle').toLowerCase();
    state.textContent = normalized === 'pending' ? 'Queued' : normalized.charAt(0).toUpperCase() + normalized.slice(1);
    state.className = `ws-run-state ${normalized === 'pending' ? 'running' : normalized}`;
  }

  function formatPipeline(result, label) {
    const lines = [];
    lines.push(`${label}: ${String(result.status || 'unknown').toUpperCase()}`);
    if (result.copilot_reply || result.reply || result.message) lines.push('', result.copilot_reply || result.reply || result.message);
    const jobs = result.jobs || [];
    jobs.forEach(job => {
      lines.push('', `${job.name || 'Autonomous task'} — ${String(job.status || 'unknown').toUpperCase()}`);
      (job.logs || []).forEach(log => lines.push(`• ${log}`));
    });
    (result.checks || []).forEach(check => {
      lines.push(`• ${check.name}: ${check.status}${check.summary ? ` — ${check.summary}` : ''}`);
    });
    (result.logs || []).forEach(log => {
      if (!lines.includes(`• ${log}`)) lines.push(`• ${log}`);
    });
    if (result.started_at) lines.push('', `Started: ${new Date(result.started_at).toLocaleString()}`);
    if (result.finished_at) lines.push(`Finished: ${new Date(result.finished_at).toLocaleString()}`);
    return lines.join('\n');
  }

  async function waitForPipeline(pipelineId, label) {
    const deadline = Date.now() + 10 * 60 * 1000;
    while (Date.now() < deadline) {
      const pipeline = await api(`/api/v1/pipelines/${encodeURIComponent(pipelineId)}`);
      setRunState(pipeline.status);
      output.textContent = formatPipeline(pipeline, label);
      if (['success', 'failed', 'cancelled'].includes(String(pipeline.status).toLowerCase())) return pipeline;
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
    throw new Error('Autonomous did not finish within 10 minutes. The task may still be running in the background.');
  }

  async function run(mode, label) {
    setRunState('running');
    output.textContent = `${label} started for ${repository?.name || 'repository'} on ${branch()}…\n\nAutonomous is inspecting the repository. Keep this page open for live results.`;
    try {
      const result = await api('/api/v1/agent/run', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          objective: `${label} repository ${repository.name} on branch ${branch()} using .Amosclaud-workflow/workflow.yml. Diagnose every blocker, report the exact failing check, and do not report success without verified evidence.`,
          branch: branch(),
          metadata: {
            repository_id: Number(repositoryId),
            repository_name: repository.name,
            use_agent: true,
            source: 'repository-autonomous-control-panel',
          },
        }),
      });
      setRunState(result.status);
      output.textContent = formatPipeline(result, label);
      if (result.pipeline_id && ['pending', 'running'].includes(String(result.status).toLowerCase())) {
        await waitForPipeline(result.pipeline_id, label);
      }
    } catch (error) {
      setRunState('failed');
      output.textContent = `${label} could not finish.\n\nExact problem: ${error.message}\n\nNo repository files were changed by this failed request.`;
    }
  }

  function replaceHandler(id, mode, label) {
    const oldButton = document.getElementById(id);
    if (!oldButton) return;
    const button = oldButton.cloneNode(true);
    oldButton.replaceWith(button);
    button.addEventListener('click', () => run(mode, label));
  }

  (async () => {
    try {
      repository = await api(`/api/v1/repositories/${repositoryId}`);
      replaceHandler('ws-build', 'build', 'Build');
      replaceHandler('ws-test', 'autonomous-check', 'Tests');
      replaceHandler('ws-review', 'autonomous-check', 'Review');
      replaceHandler('ws-deploy', 'deploy', 'Deployment preparation');
    } catch (error) {
      setRunState('failed');
      output.textContent = `Workspace setup failed: ${error.message}`;
    }
  })();
})();