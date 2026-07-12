const repositoryGrid = document.getElementById('repository-grid');
const repositoryCount = document.getElementById('repository-count');

async function apiRequest(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  if (response.status === 401) {
    window.location.assign('/login');
    throw new Error('Authentication required');
  }
  const data = response.status === 204 ? null : await response.json();
  if (!response.ok) throw new Error(data?.detail || `Request failed (${response.status})`);
  return data;
}

async function loadCurrentUser() {
  try {
    const user = await apiRequest('/api/v1/auth/me');
    document.getElementById('current-user').textContent = user.name || user.email;
  } catch (error) {
    console.error('[Current user]', error);
  }
}

async function loadRepositories() {
  try {
    const repositories = await apiRequest('/api/v1/repositories');
    repositoryCount.textContent = `${repositories.length} ${repositories.length === 1 ? 'repository' : 'repositories'}`;
    if (!repositories.length) {
      repositoryGrid.innerHTML = '<div class="repository-empty">No repositories yet. Create your first one above.</div>';
      return;
    }
    repositoryGrid.innerHTML = repositories.map(repository => `
      <article class="repository-card">
        <div class="repository-card-header">
          <h3>${escapeHtml(repository.owner_name)}/${escapeHtml(repository.name)}</h3>
          <span class="badge badge-default ${repository.visibility === 'public' ? 'visibility-public' : 'visibility-private'}">${escapeHtml(repository.visibility)}</span>
        </div>
        <p>${escapeHtml(repository.description || 'No description yet.')}</p>
        <div class="repository-meta">
          <span>Branch: ${escapeHtml(repository.default_branch)}</span>
          <span>Role: ${escapeHtml(repository.role)}</span>
          <span>Updated: ${fmtDate(repository.updated_at)}</span>
        </div>
        <div class="repository-actions">
          <button class="btn-primary" type="button" data-action="new-file" data-repository-id="${repository.id}" data-branch="${escapeHtml(repository.default_branch)}">+ File / Folder</button>
          <button class="btn-ghost" type="button" data-action="view-tree" data-repository-id="${repository.id}">Browse</button>
        </div>
        <div id="repository-tree-${repository.id}" class="repository-tree hidden"></div>
      </article>
    `).join('');
  } catch (error) {
    repositoryGrid.innerHTML = `<div class="repository-empty">${escapeHtml(error.message)}</div>`;
  }
}

async function showTree(repositoryId) {
  const container = document.getElementById(`repository-tree-${repositoryId}`);
  container.classList.remove('hidden');
  container.textContent = 'Loading files…';
  try {
    const entries = await apiRequest(`/api/v1/repositories/${repositoryId}/tree`);
    container.innerHTML = entries.length
      ? entries.map(entry => `<div class="tree-row"><span>${entry.type === 'directory' ? '📁' : '📄'}</span><span>${escapeHtml(entry.path)}</span></div>`).join('')
      : '<div class="tree-row muted">Repository is empty.</div>';
  } catch (error) {
    container.textContent = error.message;
  }
}

repositoryGrid.addEventListener('click', event => {
  const button = event.target.closest('button[data-action]');
  if (!button) return;
  const repositoryId = button.dataset.repositoryId;
  if (button.dataset.action === 'view-tree') {
    showTree(repositoryId);
  } else if (button.dataset.action === 'new-file') {
    document.getElementById('file-repository-id').value = repositoryId;
    document.getElementById('file-branch-input').value = button.dataset.branch || 'main';
    document.getElementById('file-path-input').value = '';
    document.getElementById('file-content-input').value = '';
    document.getElementById('file-commit-input').value = 'Create file';
    openModal('modal-file');
  }
});

document.getElementById('btn-create-repository').addEventListener('click', () => openModal('modal-repository'));
document.getElementById('btn-cancel-repository').addEventListener('click', closeModals);
document.getElementById('btn-cancel-file').addEventListener('click', closeModals);

document.getElementById('btn-confirm-repository').addEventListener('click', async () => {
  const name = document.getElementById('repository-name-input').value.trim();
  if (!name) return showToast('Repository name is required', 'error');
  try {
    await apiRequest('/api/v1/repositories', {
      method: 'POST',
      body: JSON.stringify({
        name,
        description: document.getElementById('repository-description-input').value.trim(),
        visibility: document.getElementById('repository-visibility-input').value,
        initialize_readme: document.getElementById('repository-readme-input').checked,
      }),
    });
    closeModals();
    document.getElementById('repository-name-input').value = '';
    document.getElementById('repository-description-input').value = '';
    showToast(`Repository "${name}" created`, 'success');
    loadRepositories();
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.getElementById('btn-confirm-file').addEventListener('click', async () => {
  const repositoryId = document.getElementById('file-repository-id').value;
  const path = document.getElementById('file-path-input').value.trim();
  if (!path) return showToast('File path is required', 'error');
  try {
    await apiRequest(`/api/v1/repositories/${repositoryId}/files`, {
      method: 'PUT',
      body: JSON.stringify({
        path,
        content: document.getElementById('file-content-input').value,
        branch: document.getElementById('file-branch-input').value.trim() || 'main',
        commit_message: document.getElementById('file-commit-input').value.trim() || 'Update file',
      }),
    });
    closeModals();
    showToast(`Committed ${path}`, 'success');
    loadRepositories();
  } catch (error) {
    showToast(error.message, 'error');
  }
});

document.getElementById('btn-logout').addEventListener('click', async () => {
  try {
    await apiRequest('/api/v1/auth/logout', { method: 'POST' });
  } finally {
    window.location.assign('/login');
  }
});

loadCurrentUser();
loadRepositories();
