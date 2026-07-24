(() => {
  const $ = id => document.getElementById(id);
  let selected = null;

  async function api(path, options = {}) {
    const response = await fetch(path, {credentials:'same-origin', ...options, headers:{...(options.body?{'Content-Type':'application/json'}:{}), ...(options.headers||{})}});
    if (response.status === 401) { location.assign('/login'); throw new Error('Sign in required'); }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail || data;
      if (response.status === 402 && detail && detail.code === 'agent_tokens_required') {
        throw new Error('Amosclaud-bot execution is not enabled for this account yet. The issue was not created. An administrator can enable execution access from API Access.');
      }
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return data;
  }
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const message = text => { $('message').textContent = text; };

  async function loadProjects() {
    const projects = await api('/api/v1/projects');
    $('projects').innerHTML = projects.length ? projects.map(p => `<div class="item" data-project="${esc(p.id)}"><strong>${esc(p.name)}</strong><div class="muted">${esc(p.repository || 'No repository')}</div></div>`).join('') : '<p class="muted">No projects yet.</p>';
  }

  async function openProject(id) {
    selected = id;
    const [project, results] = await Promise.all([api(`/api/v1/projects/${encodeURIComponent(id)}`), api(`/api/v1/projects/${encodeURIComponent(id)}/results`)]);
    $('empty').hidden = true; $('detail').hidden = false;
    $('detail-name').textContent = project.name;
    $('detail-description').textContent = project.description || 'No description';
    $('detail-repository').textContent = project.repository || 'No connected repository';
    const issues = project.issues || [];
    $('issues').innerHTML = issues.length ? issues.map(i => `<article class="item"><strong>${esc(i.title)}</strong> <span class="status">${esc(i.state)}</span><p>${esc(i.body || '')}</p><div class="muted">${esc((i.labels || []).join(', '))}${i.task_id ? ` · Task ${esc(i.task_id)}` : ''}</div></article>`).join('') : '<p class="muted">No issues yet.</p>';
    $('results').innerHTML = results.length ? results.map(r => `<article class="item"><strong>${esc(r.status)}</strong><p>${esc(r.summary || 'Task is still running.')}</p><div class="muted">Task ${esc(r.id)}${r.pull_request_url ? ` · <a href="${esc(r.pull_request_url)}">Pull request</a>` : ''}</div></article>`).join('') : '<p class="muted">No completed results yet.</p>';
  }

  $('projects').addEventListener('click', event => { const item = event.target.closest('[data-project]'); if (item) openProject(item.dataset.project).catch(e => message(e.message)); });
  $('project-form').addEventListener('submit', async event => {
    event.preventDefault();
    try {
      const project = await api('/api/v1/projects', {method:'POST', body:JSON.stringify({name:$('project-name').value, description:$('project-description').value, repository:$('project-repository').value || null})});
      event.target.reset(); await loadProjects(); await openProject(project.id); message('Project created.');
    } catch (e) { message(e.message); }
  });
  $('issue-form').addEventListener('submit', async event => {
    event.preventDefault(); if (!selected) return;
    try {
      await api(`/api/v1/projects/${encodeURIComponent(selected)}/issues`, {method:'POST', body:JSON.stringify({title:$('issue-title').value, body:$('issue-body').value, labels:$('issue-labels').value.split(',').map(v=>v.trim()).filter(Boolean), mode:$('issue-mode').value, start_work:$('issue-start').checked})});
      event.target.reset(); $('issue-start').checked = true; await openProject(selected); message('Real issue created and connected to Amosclaud-bot.');
    } catch (e) { message(e.message); }
  });
  loadProjects().catch(e => message(e.message));
})();
