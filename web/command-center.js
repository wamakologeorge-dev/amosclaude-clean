(() => {
  const $ = (id) => document.getElementById(id);
  const notice = $('notice'), repositorySelect = $('repository-select');
  let repositories = [];

  const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[char]);
  async function request(path, options = {}) {
    const response = await fetch(path, { credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
    if (response.status === 401) { window.location.assign('/login'); throw new Error('Sign in required'); }
    if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || 'Request failed'); }
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
  repositorySelect.addEventListener('change', () => { renderRepository(); loadIssues().catch(showError); });
  function showError(error) { notice.textContent = error.message || 'Request failed.'; }

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
    try { const result = await request('/api/v1/agent/run', { method: 'POST', body: JSON.stringify({ mode: 'autonomous-check', objective: $('agent-objective').value.trim(), branch: repository.default_branch, metadata: { repository_id: repository.id, repository_name: repository.name, source: 'command-center' } }) }); const output = $('agent-result'); output.hidden = false; output.textContent = result.reply || `Task ${result.status || 'accepted'}.`; notice.textContent = `Agent task ${result.status || 'accepted'}.`; } catch (error) { showError(error); }
  });
  loadRepositories().catch(showError);
})();
