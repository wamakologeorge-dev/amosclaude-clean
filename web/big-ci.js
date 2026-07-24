(() => {
  const runs = document.querySelector('#runs');
  const message = document.querySelector('#message');
  const repositorySelect = document.querySelector('#repository');
  const detail = document.querySelector('#detail');
  const detailBody = document.querySelector('#detail-body');
  const detailTitle = document.querySelector('#detail-title');
  const logs = document.querySelector('#logs');

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      cache: 'no-store',
      ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
    });
    if (response.status === 401) {
      location.assign('/login');
      throw new Error('Authentication required');
    }
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = { detail: text }; }
    if (!response.ok) {
      const detail = payload?.detail;
      const errorMessage = typeof detail === 'object'
        ? (detail.code === 'agent_tokens_required' ? 'Agent credits are required before BIG CI can start.' : JSON.stringify(detail))
        : (detail || `Request failed (${response.status})`);
      throw new Error(errorMessage);
    }
    return payload;
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function isBigCi(task) {
    return task?.mode === 'test' && task?.metadata?.product === 'big-ci';
  }

  async function loadRepositories() {
    const repositories = await api('/api/v1/repositories');
    repositorySelect.innerHTML = '<option value="">Select repository</option>' + repositories.map(repository => {
      const fullName = repository.github_full_name || `${repository.owner_name}/${repository.name}`;
      return `<option value="${escapeHtml(fullName)}" data-branch="${escapeHtml(repository.default_branch || 'main')}">${escapeHtml(fullName)}</option>`;
    }).join('');
  }

  repositorySelect.addEventListener('change', () => {
    const selected = repositorySelect.selectedOptions[0];
    if (selected?.dataset.branch) document.querySelector('#branch').value = selected.dataset.branch;
  });

  async function loadRuns() {
    try {
      const tasks = (await api('/api/v1/tasks?limit=100')).filter(isBigCi);
      if (!tasks.length) {
        runs.innerHTML = '<p class="empty">No BIG CI runs yet. Select a repository and start the first full verification.</p>';
        return;
      }
      runs.innerHTML = tasks.map(task => `
        <article class="run-card">
          <div class="top"><div><span class="status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</span><h3>${escapeHtml(task.metadata?.test_level || 'BIG CI')} · ${escapeHtml(task.repository || 'Repository')}</h3></div><span class="meta">${escapeHtml(new Date(task.created_at).toLocaleString())}</span></div>
          <p class="meta">Branch: ${escapeHtml(task.metadata?.branch || 'main')} · Target: ${escapeHtml(task.execution_target)} · Task: ${escapeHtml(task.id)}</p>
          <p>${escapeHtml(task.summary || task.objective)}</p>
          <div class="actions"><button data-open="${escapeHtml(task.id)}" class="secondary">View full results</button>${task.status === 'failed' ? `<button data-fixer="${escapeHtml(task.id)}">Send to Amosclaud Fixer</button>` : ''}${task.pull_request_url ? `<a href="${escapeHtml(task.pull_request_url)}" target="_blank" rel="noreferrer">Open pull request</a>` : ''}</div>
        </article>`).join('');
    } catch (error) {
      runs.innerHTML = `<p class="empty">${escapeHtml(error.message)}</p>`;
    }
  }

  async function openRun(taskId) {
    const [task, timeline] = await Promise.all([api(`/api/v1/tasks/${taskId}`), api(`/api/v1/tasks/${taskId}/logs`)]);
    detail.hidden = false;
    detailTitle.textContent = `${task.metadata?.test_level || 'BIG CI'} · ${task.repository || task.id}`;
    const artifacts = task.artifacts || [];
    detailBody.innerHTML = `<div class="grid"><article><b>Status</b><p class="status ${escapeHtml(task.status)}">${escapeHtml(task.status)}</p></article><article><b>Branch</b><p>${escapeHtml(task.metadata?.branch || 'main')}</p></article><article><b>Execution</b><p>${escapeHtml(task.execution_target)}</p></article><article><b>Created</b><p>${escapeHtml(new Date(task.created_at).toLocaleString())}</p></article></div><h3>Summary</h3><p>${escapeHtml(task.summary || 'The run has not produced a final summary yet.')}</p><h3>Artifacts</h3>${artifacts.length ? `<ul>${artifacts.map(item => `<li>${escapeHtml(item.name || item.path || item.url || JSON.stringify(item))}</li>`).join('')}</ul>` : '<p class="meta">No artifacts have been recorded yet.</p>'}`;
    logs.textContent = timeline.length ? timeline.map(event => `[${event.created_at}] ${event.event_type}\n${event.message}${Object.keys(event.details || {}).length ? `\n${JSON.stringify(event.details, null, 2)}` : ''}`).join('\n\n') : 'No task events have been recorded yet.';
    detail.scrollIntoView({ behavior: 'smooth' });
  }

  async function sendToFixer(taskId) {
    const failed = await api(`/api/v1/tasks/${taskId}`);
    const task = await api('/api/v1/tasks', { method: 'POST', body: JSON.stringify({
      objective: `Diagnose and repair the failed BIG CI run ${taskId}. Use its recorded logs and evidence, run targeted verification, then rerun the complete suite.`,
      repository: failed.repository,
      mode: 'fix',
      delivery: 'pull_request',
      execution_target: failed.execution_target || 'github',
      require_approval: true,
      metadata: { product: 'amosclaud-fixer', source_ci_task_id: taskId, branch: failed.metadata?.branch || 'main' },
    }) });
    message.textContent = `Amosclaud Fixer task ${task.id} was created and is awaiting approval.`;
    loadRuns();
  }

  document.querySelector('#ci-form').addEventListener('submit', async event => {
    event.preventDefault();
    message.textContent = 'Creating BIG CI run…';
    try {
      const repository = repositorySelect.value;
      if (!repository) throw new Error('Select a repository');
      const branch = document.querySelector('#branch').value.trim() || 'main';
      const level = document.querySelector('#level').value;
      const target = document.querySelector('#target').value;
      const task = await api('/api/v1/tasks', { method: 'POST', body: JSON.stringify({
        objective: `Run ${level === 'big' ? 'the complete Amosclaud BIG CI suite' : `${level} CI`} for ${repository} on branch ${branch}. Execute repository inspection, compilation, lint, unit and integration tests, API and frontend contracts, security checks, build validation, deployment readiness, and Doctor verification where supported. Record all passed, failed, skipped checks, logs, artifacts, and exact failure evidence.`,
        repository,
        mode: 'test',
        delivery: 'report',
        execution_target: target,
        require_approval: false,
        metadata: { product: 'big-ci', test_level: level, branch, requested_from: 'amosclaud-platform' },
      }) });
      message.textContent = `BIG CI task ${task.id} started with status ${task.status}.`;
      await loadRuns();
      await openRun(task.id);
    } catch (error) { message.textContent = error.message; }
  });

  runs.addEventListener('click', event => {
    const open = event.target.closest('[data-open]');
    if (open) openRun(open.dataset.open).catch(error => { message.textContent = error.message; });
    const fixer = event.target.closest('[data-fixer]');
    if (fixer) sendToFixer(fixer.dataset.fixer).catch(error => { message.textContent = error.message; });
  });
  document.querySelector('#refresh').addEventListener('click', loadRuns);
  document.querySelector('#close-detail').addEventListener('click', () => { detail.hidden = true; });

  Promise.all([loadRepositories(), loadRuns()]).catch(error => { message.textContent = error.message; });
  setInterval(loadRuns, 15000);
})();
