(() => {
  const createModal = document.getElementById('modal-repository');
  const createButton = document.getElementById('btn-create-repository');
  const confirmCreateButton = document.getElementById('btn-confirm-repository');
  const repositoryGrid = document.getElementById('repository-grid');
  if (!createModal || !createButton || !confirmCreateButton || !repositoryGrid) return;

  const visibilityLabel = document.getElementById('repository-visibility-input')?.closest('label');
  const ownerLabel = document.createElement('label');
  ownerLabel.id = 'github-owner-label';
  ownerLabel.innerHTML = `GitHub owner
    <select id="repository-github-owner-input" disabled>
      <option value="">Loading GitHub owners…</option>
    </select>
    <small id="repository-github-owner-note">Choose your personal account or an organization that authorized Amosclaud.</small>`;
  visibilityLabel?.before(ownerLabel);

  const createOwnerInput = ownerLabel.querySelector('select');
  const createOwnerNote = ownerLabel.querySelector('small');

  const publishModal = document.createElement('div');
  publishModal.id = 'modal-publish-github';
  publishModal.className = 'modal hidden';
  publishModal.setAttribute('role', 'dialog');
  publishModal.setAttribute('aria-labelledby', 'modal-publish-github-title');
  publishModal.innerHTML = `
    <h3 id="modal-publish-github-title">Publish workspace to GitHub</h3>
    <input id="publish-repository-id" type="hidden" />
    <input id="publish-branch" type="hidden" value="main" />
    <label>GitHub owner
      <select id="publish-github-owner" disabled>
        <option value="">Loading GitHub owners…</option>
      </select>
    </label>
    <label>Repository name
      <input id="publish-github-name" type="text" maxlength="100" />
    </label>
    <label>Visibility
      <select id="publish-github-visibility">
        <option value="private">Private</option>
        <option value="public">Public</option>
      </select>
    </label>
    <label>Commit message
      <input id="publish-github-commit" type="text" maxlength="200" value="Publish Amosclaud work to GitHub" />
    </label>
    <small id="publish-github-note">GitHub verifies your organization permission when publishing.</small>
    <div class="modal-actions">
      <button id="btn-cancel-publish-github" class="btn-ghost" type="button">Cancel</button>
      <button id="btn-confirm-publish-github" class="btn-primary" type="button">Publish and push</button>
    </div>`;
  document.body.appendChild(publishModal);

  const publishOwnerInput = publishModal.querySelector('#publish-github-owner');
  const publishNote = publishModal.querySelector('#publish-github-note');
  const publishIdInput = publishModal.querySelector('#publish-repository-id');
  const publishBranchInput = publishModal.querySelector('#publish-branch');
  const publishNameInput = publishModal.querySelector('#publish-github-name');
  const publishVisibilityInput = publishModal.querySelector('#publish-github-visibility');
  const publishCommitInput = publishModal.querySelector('#publish-github-commit');
  const confirmPublishButton = publishModal.querySelector('#btn-confirm-publish-github');

  let targets = [];
  let targetsLoaded = false;

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  function toast(message, type = 'info') {
    const node = document.createElement('div');
    node.className = `toast toast--${type}`;
    node.textContent = message;
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      container.setAttribute('aria-live', 'assertive');
      document.body.appendChild(container);
    }
    container.appendChild(node);
    setTimeout(() => node.remove(), 5000);
  }

  function showModal(modal) {
    document.getElementById('modal-backdrop')?.classList.remove('hidden');
    modal.classList.remove('hidden');
  }

  function hidePublishModal() {
    publishModal.classList.add('hidden');
    if (!document.querySelector('.modal:not(.hidden)')) {
      document.getElementById('modal-backdrop')?.classList.add('hidden');
    }
  }

  async function request(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers: {
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
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

  function ownerOptions() {
    return targets.map(target => (
      `<option value="${escapeHtml(target.login)}">${escapeHtml(target.login)} · ${target.kind === 'organization' ? 'organization' : 'personal account'}</option>`
    )).join('');
  }

  function renderTargets(result) {
    targets = Array.isArray(result.targets) ? result.targets : [];
    const options = ownerOptions();
    createOwnerInput.innerHTML = options || '<option value="">No authorized owners</option>';
    publishOwnerInput.innerHTML = options || '<option value="">No authorized owners</option>';
    createOwnerInput.disabled = targets.length === 0;
    publishOwnerInput.disabled = targets.length === 0;
    targetsLoaded = targets.length > 0;

    const reconnect = 'Organization visibility or workflow publishing is not fully authorized. <a href="/api/v1/github/connect-organizations">Reconnect GitHub for organization publishing</a>.';
    const note = result.reconnect_required
      ? reconnect
      : escapeHtml(result.permission_note || 'GitHub verifies your permission when the repository is created.');
    createOwnerNote.innerHTML = note;
    publishNote.innerHTML = note;
  }

  async function loadTargets(force = false) {
    if (targetsLoaded && !force) return;
    createOwnerInput.disabled = true;
    publishOwnerInput.disabled = true;
    createOwnerInput.innerHTML = '<option value="">Loading GitHub owners…</option>';
    publishOwnerInput.innerHTML = '<option value="">Loading GitHub owners…</option>';
    createOwnerNote.textContent = 'Checking the organizations available to your GitHub authorization.';
    publishNote.textContent = createOwnerNote.textContent;
    try {
      renderTargets(await request('/api/v1/github/organizations'));
    } catch (error) {
      const reconnect = `${escapeHtml(error.message)} <a href="/api/v1/github/connect-organizations">Reconnect GitHub</a>.`;
      createOwnerInput.innerHTML = '<option value="">GitHub reconnect required</option>';
      publishOwnerInput.innerHTML = '<option value="">GitHub reconnect required</option>';
      createOwnerNote.innerHTML = reconnect;
      publishNote.innerHTML = reconnect;
    }
  }

  function enhanceRepositoryCards() {
    repositoryGrid.querySelectorAll('.repository-card').forEach(card => {
      if (card.dataset.repositoryRole !== 'owner' || card.querySelector('.github-publish-existing')) return;
      const actions = card.querySelector('.repository-actions');
      const repositoryId = card.dataset.repositoryId;
      if (!actions || !repositoryId) return;
      const button = document.createElement('button');
      button.className = 'btn-ghost github-publish-existing';
      button.type = 'button';
      button.dataset.repositoryId = repositoryId;
      button.textContent = 'Publish / push GitHub';
      actions.appendChild(button);
    });
  }

  async function publishOrPushExisting(button) {
    const repositoryId = button.dataset.repositoryId;
    const card = button.closest('.repository-card');
    const name = card?.querySelector('h3')?.textContent?.split('/').pop()?.trim() || 'project';
    const branch = card?.querySelector('[data-action="new-file"]')?.dataset.branch || 'main';
    button.disabled = true;
    button.textContent = 'Checking GitHub…';
    try {
      const status = await request(`/api/v1/repositories/${encodeURIComponent(repositoryId)}/real-status`);
      if (status.remote_created) {
        button.textContent = 'Pushing…';
        const pushed = await request(`/api/v1/github/repositories/${encodeURIComponent(repositoryId)}/push`, {
          method: 'POST',
          body: JSON.stringify({
            branch,
            commit_message: 'Push Amosclaud workspace changes',
          }),
        });
        toast(`Pushed ${status.github_full_name} at ${String(pushed.commit).slice(0, 7)}`, 'success');
        return;
      }

      await loadTargets();
      publishIdInput.value = repositoryId;
      publishBranchInput.value = branch;
      publishNameInput.value = name;
      publishVisibilityInput.value = 'private';
      publishCommitInput.value = 'Publish Amosclaud work to GitHub';
      showModal(publishModal);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Publish / push GitHub';
    }
  }

  createButton.addEventListener('click', () => { loadTargets(); });

  confirmCreateButton.addEventListener('click', async event => {
    event.preventDefault();
    event.stopImmediatePropagation();

    const name = document.getElementById('repository-name-input')?.value.trim();
    if (!name) return toast('Repository name is required', 'error');
    if (!createOwnerInput.value) return toast('Choose an authorized GitHub owner', 'error');

    confirmCreateButton.disabled = true;
    confirmCreateButton.textContent = 'Creating and pushing…';
    try {
      const repository = await request('/api/v1/repositories/create-real', {
        method: 'POST',
        body: JSON.stringify({
          name,
          owner: createOwnerInput.value,
          description: document.getElementById('repository-description-input')?.value.trim() || '',
          visibility: document.getElementById('repository-visibility-input')?.value || 'private',
          initialize_readme: Boolean(document.getElementById('repository-readme-input')?.checked),
          initialize_gitignore: Boolean(document.getElementById('repository-gitignore-input')?.checked),
          license: document.getElementById('repository-license-input')?.value || 'none',
        }),
      });
      localStorage.setItem('amosclaud-last-repository-id', String(repository.id));
      localStorage.setItem('amosclaud-last-repository-name', repository.github_full_name || repository.name);
      toast(`Created and pushed ${repository.github_full_name} with Amosclaud CI`, 'success');
      window.location.assign(repository.workspace_url || `/workspace/${encodeURIComponent(repository.id)}`);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      confirmCreateButton.disabled = false;
      confirmCreateButton.textContent = 'Create repository';
    }
  }, true);

  repositoryGrid.addEventListener('click', event => {
    const button = event.target.closest('.github-publish-existing');
    if (!button) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    publishOrPushExisting(button);
  }, true);

  confirmPublishButton.addEventListener('click', async () => {
    if (!publishOwnerInput.value) return toast('Choose an authorized GitHub owner', 'error');
    if (!publishNameInput.value.trim()) return toast('Repository name is required', 'error');
    confirmPublishButton.disabled = true;
    confirmPublishButton.textContent = 'Publishing…';
    try {
      const result = await request(`/api/v1/github/repositories/${encodeURIComponent(publishIdInput.value)}/publish`, {
        method: 'POST',
        body: JSON.stringify({
          owner: publishOwnerInput.value,
          repository_name: publishNameInput.value.trim(),
          visibility: publishVisibilityInput.value,
          branch: publishBranchInput.value || 'main',
          commit_message: publishCommitInput.value.trim() || 'Publish Amosclaud work to GitHub',
        }),
      });
      hidePublishModal();
      toast(`Published ${result.github_full_name} at ${String(result.commit).slice(0, 7)}`, 'success');
      window.location.reload();
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      confirmPublishButton.disabled = false;
      confirmPublishButton.textContent = 'Publish and push';
    }
  });

  publishModal.querySelector('#btn-cancel-publish-github').addEventListener('click', hidePublishModal);
  document.getElementById('modal-backdrop')?.addEventListener('click', hidePublishModal);

  new MutationObserver(enhanceRepositoryCards).observe(repositoryGrid, {
    childList: true,
    subtree: true,
  });
  enhanceRepositoryCards();
})();
