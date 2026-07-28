(() => {
  const params = new URLSearchParams(window.location.search);
  const repositoryId = Number(params.get('repository_id'));
  const intentHeaders = { 'Content-Type': 'application/json', 'X-Amosclaud-Intent': 'repository-management' };
  let repository = null;

  const byId = id => document.getElementById(id);

  function showToast(message, isError = false) {
    const item = document.createElement('div');
    item.className = `toast${isError ? ' error' : ''}`;
    item.textContent = message;
    byId('toast-container').appendChild(item);
    setTimeout(() => item.remove(), 5000);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      ...options,
      headers: { ...(options.body ? intentHeaders : {}), ...(options.headers || {}) },
    });
    if (response.status === 401) {
      window.location.assign('/login');
      throw new Error('Sign in is required');
    }
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = { detail: text }; }
    if (!response.ok) throw new Error(payload?.detail || `Request failed (${response.status})`);
    return payload;
  }

  function requireRepository() {
    if (!repository) throw new Error('Repository settings are not loaded');
    return repository;
  }

  function confirmation() {
    const value = byId('danger-confirmation').value.trim();
    if (value !== requireRepository().full_name) {
      throw new Error(`Type ${requireRepository().full_name} exactly to continue`);
    }
    return value;
  }

  function setVisible(visible) {
    ['permissions-card', 'general-card', 'variables-card', 'secrets-card', 'webhooks-card', 'danger-card']
      .forEach(id => { byId(id).hidden = !visible; });
  }

  function fillRepository(summary) {
    repository = summary.repository;
    byId('repository-name').textContent = repository.full_name;
    byId('confirmation-name').textContent = repository.full_name;
    byId('admin-permission').textContent = summary.can_admin ? 'Administrator' : 'Not available';
    byId('repository-visibility').textContent = repository.visibility;
    byId('repository-archive-state').textContent = repository.archived ? 'Archived' : 'Active';
    byId('delete-permission').textContent = repository.delete_ready ? 'Authorized' : 'Reconnect required';
    byId('elevated-connect').hidden = repository.delete_ready;

    byId('setting-description').value = repository.description || '';
    byId('setting-homepage').value = repository.homepage || '';
    byId('setting-default-branch').value = repository.default_branch || 'main';
    byId('setting-visibility').value = repository.visibility || 'private';
    byId('setting-has-issues').checked = repository.has_issues;
    byId('setting-has-projects').checked = repository.has_projects;
    byId('setting-has-wiki').checked = repository.has_wiki;
    byId('setting-has-discussions').checked = repository.has_discussions;
    byId('setting-merge').checked = repository.allow_merge_commit;
    byId('setting-squash').checked = repository.allow_squash_merge;
    byId('setting-rebase').checked = repository.allow_rebase_merge;
    byId('setting-auto-merge').checked = repository.allow_auto_merge;
    byId('setting-delete-branch').checked = repository.delete_branch_on_merge;

    byId('archive-title').textContent = repository.archived ? 'Unarchive repository' : 'Archive repository';
    byId('archive-button').textContent = repository.archived ? 'Unarchive' : 'Archive';
    byId('page-message').textContent = summary.can_admin
      ? 'Changes are applied directly to GitHub and recorded in the Amosclaud audit log.'
      : 'The connected GitHub account does not have administrator access to this repository.';
    byId('page-message').classList.toggle('error', !summary.can_admin);
    setVisible(summary.can_admin);
  }

  function row(title, subtitle, actions = '') {
    return `<div class="management-item"><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(subtitle || '')}</small></div><div class="management-actions">${actions}</div></div>`;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#039;');
  }

  async function loadSummary() {
    if (!Number.isInteger(repositoryId) || repositoryId < 1) {
      byId('page-message').textContent = 'Choose an imported GitHub repository from the repositories page.';
      byId('page-message').classList.add('error');
      return;
    }
    const summary = await api(`/api/v1/github/repository-management/repositories/${repositoryId}`);
    fillRepository(summary);
    if (summary.can_admin) await Promise.all([loadVariables(), loadSecrets(), loadWebhooks()]);
  }

  async function loadVariables() {
    const payload = await api(`/api/v1/github/repository-management/repositories/${repositoryId}/variables`);
    const list = byId('variables-list');
    list.innerHTML = payload.variables.length
      ? payload.variables.map(item => row(
          item.name,
          item.value,
          `<button class="btn-danger compact-button" data-delete-variable="${escapeHtml(item.name)}" type="button">Delete</button>`,
        )).join('')
      : '<div class="settings-message">No repository variables.</div>';
  }

  async function loadSecrets() {
    const payload = await api(`/api/v1/github/repository-management/repositories/${repositoryId}/secrets`);
    const list = byId('secrets-list');
    list.innerHTML = payload.secrets.length
      ? payload.secrets.map(item => row(
          item.name,
          `Updated ${item.updated_at || 'unknown'}`,
          `<button class="btn-danger compact-button" data-delete-secret="${escapeHtml(item.name)}" type="button">Delete</button>`,
        )).join('')
      : '<div class="settings-message">No repository secrets.</div>';
  }

  async function loadWebhooks() {
    const payload = await api(`/api/v1/github/repository-management/repositories/${repositoryId}/webhooks`);
    const list = byId('webhooks-list');
    list.innerHTML = payload.webhooks.length
      ? payload.webhooks.map(item => row(
          item.url || `Webhook ${item.id}`,
          `${item.active ? 'Active' : 'Inactive'} · ${(item.events || []).join(', ')}`,
          `<button class="btn-ghost compact-button" data-ping-webhook="${Number(item.id)}" type="button">Ping</button><button class="btn-danger compact-button" data-delete-webhook="${Number(item.id)}" type="button">Delete</button>`,
        )).join('')
      : '<div class="settings-message">No repository webhooks.</div>';
  }

  byId('settings-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const payload = await api(
        `/api/v1/github/repository-management/repositories/${repositoryId}/settings`,
        {
          method: 'PATCH',
          body: JSON.stringify({
            description: byId('setting-description').value,
            homepage: byId('setting-homepage').value,
            default_branch: byId('setting-default-branch').value,
            visibility: byId('setting-visibility').value,
            has_issues: byId('setting-has-issues').checked,
            has_projects: byId('setting-has-projects').checked,
            has_wiki: byId('setting-has-wiki').checked,
            has_discussions: byId('setting-has-discussions').checked,
            allow_merge_commit: byId('setting-merge').checked,
            allow_squash_merge: byId('setting-squash').checked,
            allow_rebase_merge: byId('setting-rebase').checked,
            allow_auto_merge: byId('setting-auto-merge').checked,
            delete_branch_on_merge: byId('setting-delete-branch').checked,
          }),
        },
      );
      repository = payload.repository;
      showToast('Developer settings saved');
      await loadSummary();
    } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
  });

  byId('variable-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const name = byId('variable-name').value.trim();
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}/variables/${encodeURIComponent(name)}`, {
        method: 'PUT', body: JSON.stringify({ value: byId('variable-value').value }),
      });
      event.target.reset();
      showToast(`${name.toUpperCase()} saved`);
      await loadVariables();
    } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
  });

  byId('secret-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const name = byId('secret-name').value.trim();
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}/secrets/${encodeURIComponent(name)}`, {
        method: 'PUT', body: JSON.stringify({ value: byId('secret-value').value }),
      });
      event.target.reset();
      showToast(`${name.toUpperCase()} encrypted and saved`);
      await loadSecrets();
    } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
  });

  byId('webhook-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = event.submitter;
    button.disabled = true;
    try {
      const events = byId('webhook-events').value.split(',').map(value => value.trim()).filter(Boolean);
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}/webhooks`, {
        method: 'POST',
        body: JSON.stringify({
          url: byId('webhook-url').value,
          events,
          active: byId('webhook-active').checked,
          secret: byId('webhook-secret').value || null,
        }),
      });
      event.target.reset();
      byId('webhook-events').value = 'push,pull_request,issues';
      byId('webhook-active').checked = true;
      showToast('Webhook connected');
      await loadWebhooks();
    } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
  });

  byId('variables-list').addEventListener('click', async event => {
    const button = event.target.closest('[data-delete-variable]');
    if (!button) return;
    button.disabled = true;
    try {
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}/variables/${encodeURIComponent(button.dataset.deleteVariable)}`, { method: 'DELETE', body: '{}' });
      showToast('Variable deleted');
      await loadVariables();
    } catch (error) { showToast(error.message, true); button.disabled = false; }
  });

  byId('secrets-list').addEventListener('click', async event => {
    const button = event.target.closest('[data-delete-secret]');
    if (!button) return;
    button.disabled = true;
    try {
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}/secrets/${encodeURIComponent(button.dataset.deleteSecret)}`, { method: 'DELETE', body: '{}' });
      showToast('Secret deleted');
      await loadSecrets();
    } catch (error) { showToast(error.message, true); button.disabled = false; }
  });

  byId('webhooks-list').addEventListener('click', async event => {
    const ping = event.target.closest('[data-ping-webhook]');
    const remove = event.target.closest('[data-delete-webhook]');
    const button = ping || remove;
    if (!button) return;
    button.disabled = true;
    try {
      if (ping) {
        await api(`/api/v1/github/repository-management/repositories/${repositoryId}/webhooks/${ping.dataset.pingWebhook}/ping`, { method: 'POST', body: '{}' });
        showToast('Webhook ping sent');
      } else {
        await api(`/api/v1/github/repository-management/repositories/${repositoryId}/webhooks/${remove.dataset.deleteWebhook}`, { method: 'DELETE', body: '{}' });
        showToast('Webhook deleted');
        await loadWebhooks();
      }
    } catch (error) { showToast(error.message, true); } finally { button.disabled = false; }
  });

  byId('archive-button').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const confirmRepository = window.prompt(`Type ${requireRepository().full_name} to confirm`);
      if (confirmRepository === null) return;
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}/archive`, {
        method: 'POST',
        body: JSON.stringify({ archived: !repository.archived, confirm_repository: confirmRepository }),
      });
      showToast(repository.archived ? 'Repository unarchived' : 'Repository archived');
      await loadSummary();
    } catch (error) { showToast(error.message, true); } finally { event.target.disabled = false; }
  });

  byId('transfer-button').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const confirmRepository = window.prompt(`Type ${requireRepository().full_name} to confirm transfer`);
      if (confirmRepository === null) return;
      const payload = await api(`/api/v1/github/repository-management/repositories/${repositoryId}/transfer`, {
        method: 'POST',
        body: JSON.stringify({
          new_owner: byId('transfer-owner').value.trim(),
          new_name: byId('transfer-name').value.trim() || null,
          confirm_repository: confirmRepository,
        }),
      });
      showToast('GitHub transfer started');
      if (payload.repository?.full_name) byId('repository-name').textContent = payload.repository.full_name;
    } catch (error) { showToast(error.message, true); } finally { event.target.disabled = false; }
  });

  byId('delete-button').addEventListener('click', async event => {
    event.target.disabled = true;
    try {
      const confirmRepository = confirmation();
      if (!byId('delete-acknowledge').checked) throw new Error('Confirm that deletion is irreversible');
      await api(`/api/v1/github/repository-management/repositories/${repositoryId}`, {
        method: 'DELETE',
        body: JSON.stringify({
          confirm_repository: confirmRepository,
          acknowledge_irreversible: true,
        }),
      });
      showToast('Repository deleted');
      window.location.assign('/repositories');
    } catch (error) { showToast(error.message, true); event.target.disabled = false; }
  });

  loadSummary().catch(error => {
    byId('page-message').textContent = error.message;
    byId('page-message').classList.add('error');
    showToast(error.message, true);
  });
})();
