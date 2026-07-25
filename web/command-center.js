(() => {
  const $ = (id) => document.getElementById(id);
  const notice = $('notice'), repositorySelect = $('repository-select');
  let repositories = [];

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
  // Never surface a bare HTTP reason phrase (e.g. "Method Not Allowed") to the
  // user. If the API sent a real, human message we keep it; otherwise we build
  // a clear one from the status code.
  function humanHttpError(response, detail) {
    const raw = String(detail || '').trim();
    const phrase = String(response.statusText || '').trim();
    if (!raw || raw.toLowerCase() === phrase.toLowerCase()) {
      return `Amosclaud could not complete this request (HTTP ${response.status}). Please try again, and if it keeps failing report this to support.`;
    }
    return raw;
  }
  async function request(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
    if (response.status === 401) { window.location.assign('/login'); throw new Error('Sign in required'); }
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(humanHttpError(response, body.detail)); }
    return response.status === 204 ? null : response.json();
  }
  function selectedRepository() { return repositories.find((repository) => String(repository.id) === repositorySelect.value); }
  function renderRepository() {
    const repository = selectedRepository();
    $('repository-details').innerHTML = repository ? `<dt>Access</dt><dd>${escapeHtml(repository.role)}</dd><dt>Branch</dt><dd>${escapeHtml(repository.default_branch)}</dd><dt>Visibility</dt><dd>${escapeHtml(repository.visibility)}</dd>` : '';
  }
  async function loadIssues() {
    const repository = selectedRepository();
    if (!repository) { $('issue-list').textContent = 'Select a repository to load issues.'; return; }
    const issues = await request(`/api/v1/repositories/${repository.id}/issues`);
    $('issue-list').innerHTML = issues.length ? issues.map((issue) => `<article><strong>#${issue.id} ${escapeHtml(issue.title)}</strong><span>${escapeHtml(issue.state)}</span><p>${escapeHtml(issue.body)}</p></article>`).join('') : 'No issues recorded for this repository.';
  }
  async function loadRepositories(selectedId) {
    repositories = await request('/api/v1/repositories');
    repositorySelect.disabled = repositories.length === 0;
    repositorySelect.innerHTML = repositories.length ? repositories.map((repository) => `<option value="${repository.id}">${escapeHtml(repository.name)}</option>`).join('') : '<option>No repositories yet</option>';
    if (selectedId && repositories.some((repository) => repository.id === selectedId)) repositorySelect.value = String(selectedId);
    renderRepository(); await loadIssues();
    notice.textContent = repositories.length ? `${repositories.length} ${repositories.length === 1 ? 'repository' : 'repositories'} available.` : 'Create a repository to begin.';
  }
  repositorySelect.addEventListener('change', () => { renderRepository(); loadIssues().catch(showError); loadEvidence().catch(() => {}); });
  function showError(error) { notice.textContent = error.message || 'Request failed.'; }

  // ---------------------------------------------------------------------
  // Truthful all-services dashboard. Renders one tile per platform service
  // with a state a real backend check proved. `unknown` is visually distinct
  // from `operational` so an observability gap is never mistaken for health.
  // ---------------------------------------------------------------------
  const SERVICE_STATES = {
    operational: { label: 'Operational', symbol: '●' },
    degraded: { label: 'Degraded', symbol: '◐' },
    unreachable: { label: 'Unreachable', symbol: '▲' },
    not_configured: { label: 'Not configured', symbol: '○' },
    disabled: { label: 'Disabled', symbol: '⊘' },
    unknown: { label: 'Unknown', symbol: '?' },
  };
  const SERVICE_ORDER = ['operational', 'degraded', 'unreachable', 'not_configured', 'disabled', 'unknown'];

  function renderServiceTile(service) {
    const meta = SERVICE_STATES[service.state] || SERVICE_STATES.unknown;
    const remediation = service.remediation
      ? `<p class="service-remediation">What to do: ${escapeHtml(service.remediation)}</p>`
      : '';
    return `<li class="service-tile" data-state="${escapeHtml(service.state)}">
      <div class="service-tile-head"><span class="service-symbol" aria-hidden="true">${meta.symbol}</span><strong class="service-name">${escapeHtml(service.name)}</strong><span class="service-state">${escapeHtml(meta.label)}</span></div>
      <p class="service-explanation">${escapeHtml(service.explanation)}</p>
      <p class="service-evidence">Evidence: ${escapeHtml(service.evidence)}</p>
      ${remediation}
    </li>`;
  }

  function renderServices(data) {
    const services = Array.isArray(data.services) ? data.services : [];
    const counts = data.summary || {};
    const parts = SERVICE_ORDER.filter((state) => counts[state]).map((state) => `${counts[state]} ${SERVICE_STATES[state].label.toLowerCase()}`);
    $('services-summary').textContent = services.length
      ? `${services.length} services — ${parts.join(', ')}.`
      : 'No services were reported by the backend.';
    $('services-checked').textContent = data.generated_at
      ? `Checked ${new Date(data.generated_at).toLocaleString()}`
      : '';
    $('services-tiles').innerHTML = services.map(renderServiceTile).join('')
      || '<li class="muted">No services were reported by the backend.</li>';
  }

  async function loadServices() {
    const refresh = $('services-refresh');
    const error = $('services-error');
    if (refresh) refresh.disabled = true;
    try {
      const data = await request('/api/v1/platform/services');
      error.hidden = true;
      error.textContent = '';
      renderServices(data);
    } catch (err) {
      // If the endpoint itself fails we must NOT render an empty or all-green
      // board: say plainly that status could not be determined.
      $('services-tiles').innerHTML = '';
      $('services-summary').textContent = 'Service status could not be determined.';
      $('services-checked').textContent = 'Last check failed';
      error.hidden = false;
      error.textContent = `The all-services check did not respond: ${err.message}`;
    } finally {
      if (refresh) refresh.disabled = false;
    }
  }

  // ---------------------------------------------------------------------
  // Runtime status: honest diagnostics instead of raw on/off model toggles.
  // Reads the existing readiness endpoint and the existing diagnostic codes.
  // ---------------------------------------------------------------------
  async function loadRuntimeStatus() {
    const recheck = $('runtime-recheck');
    if (recheck) recheck.disabled = true;
    try {
      const ready = await fetch('/ready', { credentials: 'same-origin', cache: 'no-store' }).then((response) => response.json());
      renderRuntime(window.AmosclaudRuntimeStatus.summarize(ready));
    } catch (error) {
      renderRuntime(window.AmosclaudRuntimeStatus.summarize(null));
      $('runtime-remediation').hidden = false;
      $('runtime-remediation').textContent = `Amosclaud could not read its readiness report: ${error.message}`;
    } finally {
      if (recheck) recheck.disabled = false;
    }
  }

  function renderRuntime(summary) {
    const panel = $('runtime-panel');
    panel.dataset.reachable = String(summary.reachable);
    panel.dataset.code = summary.code || '';
    $('runtime-indicator').textContent = summary.reachable ? '●' : '▲';
    $('runtime-headline').textContent = summary.headline;
    const codeBadge = $('runtime-code');
    codeBadge.hidden = !summary.code;
    codeBadge.textContent = summary.code;
    $('runtime-provider').textContent = `${summary.activePath} — ${summary.activePathState}`;
    $('runtime-reachable').textContent = summary.reachable ? 'Reachable' : 'Not reachable';
    const remediation = $('runtime-remediation');
    remediation.hidden = !summary.remediation;
    remediation.textContent = summary.remediation ? `What to do: ${summary.remediation}` : '';
    $('runtime-native-note').textContent = summary.nativeNote;
    $('runtime-key-note').textContent = summary.noKeyNote;
    $('runtime-candidate-list').innerHTML = summary.candidates.map((candidate) => {
      const state = candidate.reachable ? 'reachable' : candidate.configured ? `not reachable (${candidate.code || 'unknown'})` : 'not configured';
      return `<li><strong>${escapeHtml(candidate.label)}</strong> — ${escapeHtml(candidate.firstParty ? 'first-party' : 'external adapter')} — ${escapeHtml(state)}</li>`;
    }).join('') || '<li>No model candidates were reported.</li>';
  }

  // ---------------------------------------------------------------------
  // Task status, logs, verification checks, and real repository evidence.
  // ---------------------------------------------------------------------
  const TERMINAL = ['success', 'failed', 'cancelled'];

  function renderTask(task) {
    $('task-status').hidden = false;
    $('task-id').textContent = task.pipeline_id || task.id || '—';
    $('task-state').textContent = task.status || 'unknown';
    const checks = Array.isArray(task.checks) ? task.checks : [];
    $('task-checks').innerHTML = checks.length
      ? checks.map((check) => `<div class="task-check"><strong>${escapeHtml(check.name)}</strong><span>${escapeHtml(check.status)}</span><p>${escapeHtml(check.summary || '')}</p></div>`).join('')
      : 'No verification checks were returned.';
    const logs = Array.isArray(task.logs) ? task.logs : [];
    $('task-logs').textContent = logs.length ? logs.join('\n') : 'No logs were returned.';
  }

  function flatten(pipeline, previous) {
    const jobs = Array.isArray(pipeline.jobs) ? pipeline.jobs : [];
    return {
      pipeline_id: pipeline.id || previous.pipeline_id,
      status: pipeline.status || previous.status,
      reply: pipeline.copilot_reply || pipeline.message || previous.reply,
      checks: previous.checks || [],
      logs: jobs.flatMap((job) => (Array.isArray(job.logs) ? job.logs : [])),
    };
  }

  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  async function followTask(initial) {
    let latest = initial;
    const id = String(initial.pipeline_id || '');
    if (!id || id.startsWith('conversation-')) return latest;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      if (TERMINAL.includes(String(latest.status || '').toLowerCase())) return latest;
      await wait(1000);
      const pipeline = await request(`/api/v1/pipelines/${encodeURIComponent(id)}`);
      latest = flatten(pipeline, latest);
      renderTask(latest);
    }
    return latest;
  }

  function listItems(node, items, empty) {
    node.innerHTML = items.length ? items.join('') : `<li class="muted">${escapeHtml(empty)}</li>`;
  }

  async function loadEvidence() {
    const repository = selectedRepository();
    const panel = $('task-evidence');
    if (!repository) { panel.hidden = true; return; }
    const branch = repository.default_branch || 'main';
    const [branches, commits, pullRequests] = await Promise.all([
      request(`/api/v1/repositories/${repository.id}/branches`).catch(() => []),
      request(`/api/v1/repositories/${repository.id}/commits?branch=${encodeURIComponent(branch)}&limit=5`).catch(() => []),
      request(`/api/v1/repositories/${repository.id}/pull-requests`).catch(() => []),
    ]);
    panel.hidden = false;
    const workspace = `/workspace/${repository.id}`;
    listItems($('evidence-branches'), (branches || []).map((name) => `<li><a href="${escapeHtml(workspace)}">${escapeHtml(name)}</a></li>`), 'The backend returned no branches.');
    listItems($('evidence-commits'), (commits || []).map((commit) => `<li><code>${escapeHtml(String(commit.sha).slice(0, 10))}</code> ${escapeHtml(commit.message)}</li>`), 'The backend returned no commits.');
    listItems($('evidence-pull-requests'), (pullRequests || []).map((pull) => `<li><a href="${escapeHtml(workspace)}">#${escapeHtml(pull.id)} ${escapeHtml(pull.title)}</a> — ${escapeHtml(pull.state)} (${escapeHtml(pull.head_branch)} → ${escapeHtml(pull.base_branch)})</li>`), 'The backend returned no pull requests.');
  }

  $('repository-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    try { const repository = await request('/api/v1/repositories', { method: 'POST', body: JSON.stringify({ name: $('repository-name').value.trim(), description: $('repository-description').value.trim(), visibility: 'private', initialize_readme: true }) }); event.target.reset(); await loadRepositories(repository.id); notice.textContent = `${repository.name} was created.`; } catch (error) { showError(error); }
  });
  $('issue-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const repository = selectedRepository(); if (!repository) return showError(new Error('Choose a repository first.'));
    try { await request(`/api/v1/repositories/${repository.id}/issues`, { method: 'POST', body: JSON.stringify({ title: $('issue-title').value.trim(), body: $('issue-body').value.trim() }) }); event.target.reset(); await loadIssues(); notice.textContent = 'Issue recorded.'; } catch (error) { showError(error); }
  });
  $('agent-form').addEventListener('submit', async (event) => {
    event.preventDefault(); const repository = selectedRepository(); if (!repository) return showError(new Error('Choose a repository first.'));
    try {
      const result = await request('/api/v1/agent/run', { method: 'POST', body: JSON.stringify({ mode: 'autonomous-check', objective: $('agent-objective').value.trim(), branch: repository.default_branch, metadata: { repository_id: repository.id, repository_name: repository.name, source: 'command-center' } }) });
      const output = $('agent-result');
      output.hidden = false;
      output.textContent = result.reply || `Task ${result.status || 'accepted'}.`;
      renderTask(result);
      notice.textContent = `Agent task ${result.status || 'accepted'}.`;
      const finished = await followTask(result);
      renderTask(finished);
      output.textContent = finished.reply || output.textContent;
      notice.textContent = `Agent task ${finished.status || 'accepted'}.`;
      await loadEvidence();
    } catch (error) { showError(error); }
  });
  $('runtime-recheck').addEventListener('click', () => { loadRuntimeStatus(); });
  $('services-refresh').addEventListener('click', () => { loadServices(); });
  loadServices();
  loadRuntimeStatus();
  loadRepositories().then(() => loadEvidence()).catch(showError);
})();
