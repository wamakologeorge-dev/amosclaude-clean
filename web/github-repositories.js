(() => {
  const integrationLink = document.querySelector('a[href="/api/v1/auth/github/link"]');
  if (integrationLink) integrationLink.href = '/static/github-setup.html';

  const main = document.querySelector('.repo-main');
  if (!main || document.querySelector('.github-import-panel')) return;

  const section = document.createElement('section');
  section.className = 'github-import-panel';
  section.innerHTML = `
    <div class="repo-page-heading" style="margin-top:24px">
      <div>
        <h2>GitHub repositories</h2>
        <p id="github-connection-message">Checking your GitHub connection…</p>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <a id="github-connect-button" class="repo-dashboard-link" href="/static/github-setup.html">Set up GitHub</a>
        <button id="github-refresh-button" class="btn-ghost compact-button" type="button">Refresh</button>
      </div>
    </div>
    <div id="github-repository-grid" class="github-repository-list">
      <div class="repository-empty">Connect GitHub to browse and import repositories.</div>
    </div>
  `;
  main.appendChild(section);

  const message = section.querySelector('#github-connection-message');
  const grid = section.querySelector('#github-repository-grid');
  const refreshButton = section.querySelector('#github-refresh-button');
  const connectButton = section.querySelector('#github-connect-button');

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function toast(text, isError = false) {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.setAttribute('aria-live', 'assertive');
      document.body.appendChild(container);
    }
    const item = document.createElement('div');
    item.className = `toast${isError ? ' error' : ''}`;
    item.textContent = text;
    container.appendChild(item);
    setTimeout(() => item.remove(), 4500);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
  }

  async function activateRepository(repository, fullName = '') {
    const repositoryId = Number(repository.id || repository.imported_repository_id);
    if (!Number.isInteger(repositoryId) || repositoryId < 1) return;
    const name = repository.name || fullName.split('/').pop() || 'Repository';
    const branch = repository.default_branch || 'main';
    const context = {
      workspace_id: null,
      workspace_name: 'Personal workspace',
      repository_id: repositoryId,
      repository_name: name,
      selected_workspace: 'Personal workspace',
      selected_repository: name,
      branch,
      repository_role: 'owner',
      owner_authorization: 'session-owner',
      owner_authorized: true,
      repository_provider: 'github',
      github_full_name: fullName || repository.github_full_name || null,
      project_context_source: 'github-import',
    };
    localStorage.setItem('amosclaud.activeProjectContext', JSON.stringify(context));
    localStorage.setItem('amosclaud-last-repository-id', String(repositoryId));
    localStorage.setItem(
      'amosclaud-last-repository-name',
      fullName || repository.github_full_name || name,
    );
    window.dispatchEvent(new CustomEvent('amosclaud:project-context', { detail: context }));
    await api('/api/v1/core/os/context', {
      method: 'PUT',
      body: JSON.stringify({
        repository_id: repositoryId,
        workspace_id: null,
        branch,
      }),
    });
  }

  async function importRepository(fullName, button) {
    button.disabled = true;
    button.textContent = 'Importing…';
    try {
      const imported = await api('/api/v1/github/repositories/import', {
        method: 'POST',
        body: JSON.stringify({ full_name: fullName }),
      });
      await activateRepository(imported, fullName);
      toast(`${fullName} imported and selected for Amosclaud Agent`);
      button.textContent = 'Open workspace';
      button.disabled = false;
      button.dataset.workspace = imported.workspace_url;
      button.onclick = () => { window.location.href = imported.workspace_url; };
      document.dispatchEvent(new CustomEvent('amosclaud:repositories-changed'));
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
      button.textContent = 'Import';
    }
  }

  function renderRepositories(repositories) {
    if (!repositories.length) {
      grid.innerHTML = '<div class="repository-empty">No GitHub repositories are available to this account.</div>';
      return;
    }
    grid.innerHTML = repositories.map(repo => {
      const imported = repo.imported_repository_id;
      const action = imported
        ? `<button class="repo-dashboard-link github-open-imported" type="button" data-repository-id="${Number(imported)}" data-full-name="${escapeHtml(repo.full_name)}" data-name="${escapeHtml(repo.name)}" data-branch="${escapeHtml(repo.default_branch)}">Use in Agent</button>`
        : `<button class="btn-primary compact-button github-import-button" data-full-name="${escapeHtml(repo.full_name)}" type="button">Import</button>`;
      return `
        <article class="repository-card">
          <div class="repository-card-header">
            <div>
              <strong>${escapeHtml(repo.full_name)}</strong>
              <span class="${repo.private ? 'visibility-private' : 'visibility-public'}">${repo.private ? 'Private' : 'Public'}</span>
            </div>
          </div>
          <p>${escapeHtml(repo.description || 'No description')}</p>
          <div class="repository-card-meta">
            <span>Default branch: ${escapeHtml(repo.default_branch)}</span>
            <span>${repo.can_push ? 'Push access' : 'Read access'}</span>
          </div>
          <div class="modal-actions" style="justify-content:flex-start">${action}</div>
        </article>
      `;
    }).join('');
    grid.querySelectorAll('.github-import-button').forEach(button => {
      button.addEventListener('click', () => importRepository(button.dataset.fullName, button));
    });
    grid.querySelectorAll('.github-open-imported').forEach(button => {
      button.addEventListener('click', async () => {
        button.disabled = true;
        try {
          await activateRepository(
            {
              id: Number(button.dataset.repositoryId),
              name: button.dataset.name,
              default_branch: button.dataset.branch,
            },
            button.dataset.fullName,
          );
          toast(`${button.dataset.fullName} selected for Amosclaud Agent`);
          window.location.href = `/workspace/${encodeURIComponent(button.dataset.repositoryId)}`;
        } catch (error) {
          toast(error.message, true);
          button.disabled = false;
        }
      });
    });
  }

  async function loadGitHubRepositories() {
    refreshButton.disabled = true;
    try {
      const status = await api('/api/v1/github/status');
      if (!status.connected) {
        message.textContent = 'GitHub is not connected. Open the guided setup to configure OAuth safely.';
        connectButton.textContent = 'Set up GitHub';
        connectButton.hidden = false;
        grid.innerHTML = '<div class="repository-empty">GitHub is not connected. Amosclaud will guide the owner through the required Railway variables.</div>';
        return;
      }
      connectButton.textContent = 'GitHub settings';
      connectButton.hidden = false;
      message.textContent = `Connected as @${status.connection.github_login}. Import a repository or select one for the Agent.`;
      grid.innerHTML = '<div class="repository-empty">Loading GitHub repositories…</div>';
      const repositories = await api('/api/v1/github/repositories');
      renderRepositories(repositories);
    } catch (error) {
      message.textContent = error.message;
      grid.innerHTML = `<div class="repository-empty">${escapeHtml(error.message)}</div>`;
    } finally {
      refreshButton.disabled = false;
    }
  }

  refreshButton.addEventListener('click', loadGitHubRepositories);
  loadGitHubRepositories();
})();
