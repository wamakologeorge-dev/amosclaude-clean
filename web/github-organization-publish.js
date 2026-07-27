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
    <small id="publish-github-note">GitHub verifies permission when publishing.</small>
    <div id="publish-github-reconnect" class="modal-actions hidden">
      <span id="publish-github-reconnect-message"></span>
      <button id="btn-reconnect-publish-github" class="btn-primary" type="button">Reconnect GitHub and continue</button>
    </div>
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
  const reconnectPanel = publishModal.querySelector('#publish-github-reconnect');
  const reconnectMessage = publishModal.querySelector('#publish-github-reconnect-message');
  const reconnectButton = publishModal.querySelector('#btn-reconnect-publish-github');

  const PENDING_PUBLISH_KEY = 'amosclaud-pending-github-publish';
  let targets = [];
  let targetsLoaded = false;
  let targetResult = {
    reconnect_required: false,
    reconnect_url: '/api/v1/github/connect-organizations',
    permission_note: '',
  };

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
    setTimeout(() => node.remove(), 6500);
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
      const error = new Error(payload?.detail || `Request failed (${response.status})`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function targetFor(login = publishOwnerInput.value) {
    return targets.find(target => target.login === login) || null;
  }

  function permissionText(target, visibility = publishVisibilityInput.value) {
    if (!target) return 'Choose the GitHub account that should own this repository.';
    if (target.kind === 'user') {
      return visibility === 'private'
        ? `Publishing a private repository to ${target.login} requires GitHub repository access. Workflow access is also required when the project contains GitHub Actions files.`
        : `Publishing a public repository to ${target.login} requires public repository access. Workflow access is also required when the project contains GitHub Actions files.`;
    }
    return `Publishing to ${target.login} requires repository access plus approval from that GitHub organization. Organization policy or SSO may require an additional approval step.`;
  }

  function clearReconnectAction() {
    reconnectPanel.classList.add('hidden');
    reconnectMessage.textContent = '';
  }

  function showReconnectAction(message) {
    reconnectMessage.textContent = message;
    reconnectPanel.classList.remove('hidden');
  }

  function updatePermissionNote() {
    const target = targetFor();
    const base = permissionText(target);
    if (targetResult.reconnect_required) {
      publishNote.textContent = `${base} Your current GitHub authorization may be missing one of these permissions.`;
      showReconnectAction('Approve the requested GitHub repository and workflow permissions, then Amosclaud will restore this publish form.');
    } else {
      publishNote.textContent = targetResult.permission_note || base;
      clearReconnectAction();
    }
  }

  function ownerOptions() {
    return targets.map(target => (
      `<option value="${escapeHtml(target.login)}">${escapeHtml(target.login)} · ${target.kind === 'organization' ? 'organization' : 'personal account'}</option>`
    )).join('');
  }

  function renderTargets(result) {
    targetResult = {
      reconnect_required: Boolean(result.reconnect_required),
      reconnect_url: result.reconnect_url || '/api/v1/github/connect-organizations',
      permission_note: result.permission_note || '',
    };
    targets = Array.isArray(result.targets) ? result.targets : [];
    const options = ownerOptions();
    createOwnerInput.innerHTML = options || '<option value="">No authorized owners</option>';
    publishOwnerInput.innerHTML = options || '<option value="">No authorized owners</option>';
    createOwnerInput.disabled = targets.length === 0;
    publishOwnerInput.disabled = targets.length === 0;
    targetsLoaded = targets.length > 0;

    const createTarget = targets.find(target => target.login === createOwnerInput.value) || targets[0];
    const createBase = permissionText(createTarget, document.getElementById('repository-visibility-input')?.value || 'private');
    if (targetResult.reconnect_required) {
      createOwnerNote.innerHTML = `${escapeHtml(createBase)} <a href="${escapeHtml(targetResult.reconnect_url)}">Reconnect GitHub</a>.`;
    } else {
      createOwnerNote.textContent = targetResult.permission_note || createBase;
    }
    updatePermissionNote();
  }

  async function loadTargets(force = false) {
    if (targetsLoaded && !force) return;
    createOwnerInput.disabled = true;
    publishOwnerInput.disabled = true;
    createOwnerInput.innerHTML = '<option value="">Loading GitHub owners…</option>';
    publishOwnerInput.innerHTML = '<option value="">Loading GitHub owners…</option>';
    createOwnerNote.textContent = 'Checking the GitHub permissions available to this account.';
    publishNote.textContent = createOwnerNote.textContent;
    try {
      renderTargets(await request('/api/v1/github/organizations'));
    } catch (error) {
      targetResult.reconnect_required = true;
      const reconnect = `${escapeHtml(error.message)} <a href="/api/v1/github/connect-organizations">Reconnect GitHub</a>.`;
      createOwnerInput.innerHTML = '<option value="">GitHub reconnect required</option>';
      publishOwnerInput.innerHTML = '<option value="">GitHub reconnect required</option>';
      createOwnerNote.innerHTML = reconnect;
      publishNote.innerHTML = reconnect;
      showReconnectAction('Reconnect GitHub to restore repository publishing access.');
    }
  }

  function pendingPublish() {
    return {
      repositoryId: publishIdInput.value,
      owner: publishOwnerInput.value,
      branch: publishBranchInput.value || 'main',
      name: publishNameInput.value.trim(),
      visibility: publishVisibilityInput.value,
      commitMessage: publishCommitInput.value.trim() || 'Publish Amosclaud work to GitHub',
    };
  }

  function savePendingPublish() {
    const pending = pendingPublish();
    if (pending.repositoryId && pending.owner && pending.name) {
      sessionStorage.setItem(PENDING_PUBLISH_KEY, JSON.stringify(pending));
    }
  }

  async function restorePendingPublish() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('github') !== 'connected') return;
    let pending = null;
    try {
      pending = JSON.parse(sessionStorage.getItem(PENDING_PUBLISH_KEY) || 'null');
    } catch {
      sessionStorage.removeItem(PENDING_PUBLISH_KEY);
    }
    if (!pending?.repositoryId || !pending?.name) return;
    await loadTargets(true);
    publishIdInput.value = pending.repositoryId;
    publishBranchInput.value = pending.branch || 'main';
    publishNameInput.value = pending.name;
    publishVisibilityInput.value = pending.visibility || 'private';
    publishCommitInput.value = pending.commitMessage || 'Publish Amosclaud work to GitHub';
    if (targets.some(target => target.login === pending.owner)) {
      publishOwnerInput.value = pending.owner;
    }
    targetResult.reconnect_required = false;
    updatePermissionNote();
    publishNote.textContent = 'GitHub authorization returned successfully. Review the details, then tap Publish and push.';
    clearReconnectAction();
    showModal(publishModal);
    toast('GitHub reconnected. Your publish details were restored.', 'success');
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
      clearReconnectAction();
      updatePermissionNote();
      showModal(publishModal);
    } catch (error) {
      toast(error.message, 'error');
    } finally {
      button.disabled = false;
      button.textContent = 'Publish / push GitHub';
    }
  }

  createButton.addEventListener('click', () => { loadTargets(); });
  createOwnerInput.addEventListener('change', () => renderTargets({ ...targetResult, targets }));
  document.getElementById('repository-visibility-input')?.addEventListener('change', () => renderTargets({ ...targetResult, targets }));
  publishOwnerInput.addEventListener('change', updatePermissionNote);
  publishVisibilityInput.addEventListener('change', updatePermissionNote);

  reconnectButton.addEventListener('click', () => {
    savePendingPublish();
    window.location.assign(targetResult.reconnect_url || '/api/v1/github/connect-organizations');
  });

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
      const personal = targetFor(createOwnerInput.value)?.kind !== 'organization';
      if (error.status === 403) {
        const message = personal
          ? `GitHub did not allow repository creation in ${createOwnerInput.value}. Reconnect GitHub and approve repository access.`
          : `GitHub did not allow repository creation in ${createOwnerInput.value}. An organization owner may also need to approve Amosclaud.`;
        toast(message, 'error');
      } else {
        toast(error.message, 'error');
      }
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
    clearReconnectAction();
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
      sessionStorage.removeItem(PENDING_PUBLISH_KEY);
      hidePublishModal();
      toast(`Published ${result.github_full_name} at ${String(result.commit).slice(0, 7)}`, 'success');
      window.location.reload();
    } catch (error) {
      const target = targetFor();
      if (error.status === 401 || error.status === 403) {
        const message = target?.kind === 'organization'
          ? `GitHub did not authorize publishing to ${publishOwnerInput.value}. Reconnect GitHub; the organization may also need to approve Amosclaud and allow your role to create repositories.`
          : `GitHub did not authorize ${publishVisibilityInput.value} repository creation in your personal account ${publishOwnerInput.value}. Reconnect GitHub and approve repository access${publishVisibilityInput.value === 'private' ? ' for private repositories' : ''}.`;
        showReconnectAction(message);
        toast('GitHub permission needs approval. Use Reconnect GitHub and continue in this window.', 'error');
      } else {
        toast(error.message, 'error');
      }
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
  restorePendingPublish();
})();
