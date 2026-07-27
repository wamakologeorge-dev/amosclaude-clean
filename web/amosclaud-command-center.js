(() => {
  const state = {
    platform: document.querySelector('#platform-state'),
    repositories: document.querySelector('#repository-count'),
    workspaces: document.querySelector('#workspace-count'),
    github: document.querySelector('#github-state'),
    list: document.querySelector('#repositories'),
  };

  async function request(path) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = text ? JSON.parse(text) : null;
    } catch {
      payload = { detail: text };
    }
    if (!response.ok) {
      throw new Error(payload?.detail || `Request failed (${response.status})`);
    }
    return payload;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  async function loadPlatform() {
    try {
      const health = await request('/health');
      state.platform.textContent = health?.status || health?.ok ? 'Operational' : 'Available';
    } catch {
      state.platform.textContent = 'Unavailable';
    }
  }

  async function loadRepositories() {
    try {
      const repositories = await request('/api/v1/repositories');
      const items = Array.isArray(repositories) ? repositories : [];
      state.repositories.textContent = String(items.length);
      state.list.innerHTML = items.length
        ? items.slice(0, 12).map(repository => `
          <article class="repo">
            <header>
              <a href="/workspace/${encodeURIComponent(repository.id)}">${escapeHtml(repository.name)}</a>
              <span class="badge">${escapeHtml(repository.visibility || repository.role || 'repository')}</span>
            </header>
            <p>${escapeHtml(repository.description || 'Amosclaud repository workspace')}</p>
          </article>`).join('')
        : '<p class="muted">No repositories are connected yet.</p>';
    } catch (error) {
      state.repositories.textContent = '—';
      state.list.innerHTML = `<p class="muted">${escapeHtml(error.message)}</p>`;
    }
  }

  async function loadWorkspaces() {
    try {
      const workspaces = await request('/api/v1/workspaces');
      state.workspaces.textContent = String(Array.isArray(workspaces) ? workspaces.length : 0);
    } catch {
      state.workspaces.textContent = '—';
    }
  }

  async function loadGitHub() {
    try {
      const status = await request('/api/v1/github/status');
      state.github.textContent = status?.connected ? 'Connected' : 'Not connected';
    } catch {
      state.github.textContent = 'Unavailable';
    }
  }

  Promise.allSettled([
    loadPlatform(),
    loadRepositories(),
    loadWorkspaces(),
    loadGitHub(),
  ]);
})();
