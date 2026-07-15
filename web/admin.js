(() => {
  const byId = id => document.getElementById(id);
  const metrics = byId('admin-metrics');
  const usersBody = byId('admin-users-body');
  const repositoriesBody = byId('admin-repositories-body');
  const audit = byId('admin-audit');
  const search = byId('admin-user-search');
  const refresh = byId('admin-refresh');
  const health = byId('admin-health');
  const lastUpdated = byId('admin-last-updated');
  const ownerRuntime = byId('owner-runtime');
  const ownerRuntimeState = byId('owner-runtime-state');
  const ownerRuntimeMessage = byId('owner-runtime-message');
  const ownerServicesBody = byId('owner-services-body');
  const ownerSettingsBody = byId('owner-settings-body');
  const runtimePanel = byId('runtime-control-center');
  const snapshotNode = byId('autonomous-runtime-snapshot');

  const escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const formatDate = value => value ? new Date(value).toLocaleString() : 'Never';
  const formatBytes = bytes => {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    if (value < 1048576) return `${(value / 1024).toFixed(1)} KB`;
    if (value < 1073741824) return `${(value / 1048576).toFixed(1)} MB`;
    return `${(value / 1073741824).toFixed(1)} GB`;
  };

  function toast(message, isError = false) {
    const item = document.createElement('div');
    item.className = `admin-toast${isError ? ' error' : ''}`;
    item.textContent = message;
    byId('toast-container').appendChild(item);
    setTimeout(() => item.remove(), 4200);
  }

  async function request(path, { owner = false, ...options } = {}) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch(path, {
        credentials: 'same-origin',
        cache: owner ? 'no-store' : 'default',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        signal: controller.signal,
        ...options,
      });
      if (response.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated'); }
      if (response.status === 403 && owner) return null;
      if (response.status === 403) { window.location.href = '/'; throw new Error('Administrator access required'); }
      if (!response.ok) {
        let detail = `Request failed (${response.status})`;
        try { detail = (await response.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      return response.status === 204 ? null : response.json();
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Runtime request timed out');
      throw error;
    } finally { clearTimeout(timeout); }
  }

  function setSnapshot(payload) {
    const snapshot = {
      schema: 'amosclaud.runtime.v1',
      generated_at: new Date().toISOString(),
      ...payload,
    };
    snapshotNode.textContent = JSON.stringify(snapshot);
    runtimePanel.dataset.runtimeState = snapshot.state || 'unknown';
    runtimePanel.dataset.runtimeSchema = snapshot.schema;
    window.AmosclaudRuntimeSnapshot = Object.freeze(snapshot);
  }

  function setRuntimeState(state, message) {
    ownerRuntimeState.className = `admin-badge ${state === 'operational' ? 'ok' : state === 'degraded' ? 'warn' : 'pending'}`;
    ownerRuntimeState.textContent = state === 'operational' ? 'Operational' : state === 'degraded' ? 'Degraded' : state === 'restricted' ? 'Owner only' : 'Unavailable';
    ownerRuntimeMessage.textContent = message;
  }

  function renderMetrics(data) {
    const items = [
      ['Users', data.users], ['Administrators', data.administrators], ['Suspended', data.suspended_users],
      ['Active sessions', data.active_sessions], ['Repositories', data.repositories], ['Pipelines', data.pipelines],
      ['Deployments', data.deployments], ['Repository storage', formatBytes(data.repository_storage_bytes)],
      ['Database', formatBytes(data.database_bytes)], ['Mail messages', data.mail_messages],
      ['Community posts', data.community_posts], ['System status', data.status],
    ];
    metrics.innerHTML = items.map(([label, value]) => `<article class="admin-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></article>`).join('');
    health.textContent = data.status === 'operational' ? '● Operational' : String(data.status || 'Unknown');
  }

  function renderOwnerControl(access, model, services, settings) {
    if (settings === null) {
      setRuntimeState('restricted', 'Owner runtime details are restricted to the owner account.');
      ownerRuntime.innerHTML = '<article class="admin-metric runtime-wide"><span>Access</span><strong>Owner account required</strong><small>Sign in with the platform owner account to inspect runtime services.</small></article>';
      ownerServicesBody.innerHTML = '<tr><td colspan="4">Runtime service details are restricted.</td></tr>';
      ownerSettingsBody.innerHTML = '<tr><td colspan="4">Vault settings are restricted.</td></tr>';
      setSnapshot({ state: 'restricted', access_mode: 'owner-only', services: [] });
      return;
    }

    const safeServices = Array.isArray(services) ? services : [];
    const healthyCount = safeServices.filter(service => service.healthy).length;
    const runtimeState = model?.status === 'operational' && healthyCount === safeServices.length ? 'operational' : 'degraded';
    const runtimeItems = [
      ['Access mode', access?.mode || 'Unknown', 'Owner authorization'],
      ['Execution engine', model?.status || 'Unavailable', 'Runtime availability'],
      ['Active model', model?.model || 'Not configured', 'Configured inference target'],
      ['Registered services', `${healthyCount}/${safeServices.length} healthy`, 'Healthy service count'],
    ];
    ownerRuntime.innerHTML = runtimeItems.map(([label, value, note]) => `<article class="admin-metric" data-field="${escapeHtml(label.toLowerCase().replaceAll(' ','_'))}"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong><small>${escapeHtml(note)}</small></article>`).join('');

    ownerServicesBody.innerHTML = safeServices.length ? safeServices.map(service => `
      <tr data-service="${escapeHtml(service.name)}" data-health="${service.healthy ? 'healthy' : 'offline'}">
        <td><strong>${escapeHtml(service.name)}</strong></td>
        <td>${escapeHtml(service.kind || 'service')}</td>
        <td>${service.healthy ? '<span class="admin-badge ok">Healthy</span>' : '<span class="admin-badge warn">Offline</span>'}</td>
        <td>${formatDate(service.last_seen)}</td>
      </tr>`).join('') : '<tr><td colspan="4">No services are registered. The runtime can still operate through its internal address.</td></tr>';

    const safeSettings = Array.isArray(settings) ? settings : [];
    ownerSettingsBody.innerHTML = safeSettings.length ? safeSettings.map(setting => `
      <tr><td><strong>${escapeHtml(setting.name)}</strong></td><td>${escapeHtml(setting.value)}</td><td>${setting.is_secret ? '<span class="admin-badge admin">Secret</span>' : '<span class="admin-badge ok">Visible</span>'}</td><td>${formatDate(setting.updated_at)}</td></tr>`).join('') : '<tr><td colspan="4">No Vault settings saved. Bootstrap settings remain in the local environment file.</td></tr>';

    setRuntimeState(runtimeState, runtimeState === 'operational' ? 'All registered runtime services are healthy and readable.' : `${healthyCount} of ${safeServices.length} registered services are healthy.`);
    setSnapshot({
      state: runtimeState,
      access_mode: access?.mode || 'unknown',
      model_runtime: model?.status || 'unavailable',
      active_model: model?.model || null,
      service_summary: { registered: safeServices.length, healthy: healthyCount, offline: safeServices.length - healthyCount },
      services: safeServices.map(service => ({ name: service.name, type: service.kind, status: service.healthy ? 'healthy' : 'offline', last_seen: service.last_seen || null })),
    });
  }

  function renderRuntimeError(error) {
    setRuntimeState('unavailable', `Runtime data could not be loaded: ${error.message}`);
    ownerRuntime.innerHTML = '<article class="admin-metric runtime-wide"><span>Runtime status</span><strong>Unavailable</strong><small>Use Refresh after confirming the server and API are online.</small></article>';
    ownerServicesBody.innerHTML = `<tr><td colspan="4">${escapeHtml(error.message)}</td></tr>`;
    ownerSettingsBody.innerHTML = '<tr><td colspan="4">Vault status unavailable until the runtime connection recovers.</td></tr>';
    setSnapshot({ state: 'unavailable', error: error.message, services: [] });
  }

  function renderUsers(users) {
    usersBody.innerHTML = users.length ? users.map(user => `<tr><td><div class="admin-user"><strong>${escapeHtml(user.name)}</strong><small>${escapeHtml(user.email)}</small></div></td><td>${escapeHtml(user.provider)}</td><td>${Number(user.repository_count || 0)}</td><td>${Number(user.session_count || 0)}</td><td>${user.is_suspended ? '<span class="admin-badge warn">Suspended</span>' : '<span class="admin-badge ok">Active</span>'} ${user.is_admin ? '<span class="admin-badge admin">Admin</span>' : ''}</td><td><div class="admin-actions"><button data-action="admin" data-id="${user.id}" data-value="${user.is_admin ? 'false' : 'true'}">${user.is_admin ? 'Remove admin' : 'Make admin'}</button><button class="${user.is_suspended ? '' : 'danger'}" data-action="suspend" data-id="${user.id}" data-value="${user.is_suspended ? 'false' : 'true'}">${user.is_suspended ? 'Restore' : 'Suspend'}</button></div></td></tr>`).join('') : '<tr><td colspan="6">No users found.</td></tr>';
    usersBody.querySelectorAll('button[data-action]').forEach(button => button.addEventListener('click', async () => {
      const isAdminChange = button.dataset.action === 'admin';
      const value = button.dataset.value === 'true';
      if (!window.confirm('Apply this account change?')) return;
      try {
        await request(`/api/v1/admin/users/${button.dataset.id}`, { method: 'PATCH', body: JSON.stringify(isAdminChange ? { is_admin: value } : { is_suspended: value }) });
        toast('User updated'); await Promise.all([loadUsers(), loadOverview(), loadAudit()]);
      } catch (error) { toast(error.message, true); }
    }));
  }

  function renderRepositories(repositories) {
    repositoriesBody.innerHTML = repositories.length ? repositories.map(repo => `<tr><td><strong>${escapeHtml(repo.name)}</strong><br><small>#${repo.id}</small></td><td><div class="admin-user"><strong>${escapeHtml(repo.owner_name)}</strong><small>${escapeHtml(repo.owner_email)}</small></div></td><td>${escapeHtml(repo.visibility)}</td><td>${formatBytes(repo.storage_bytes)}</td><td>${formatDate(repo.updated_at)}</td><td><div class="admin-actions"><a href="/workspace/${repo.id}">Open</a><button class="danger" data-delete-repository="${repo.id}" data-name="${escapeHtml(repo.name)}">Delete</button></div></td></tr>`).join('') : '<tr><td colspan="6">No repositories found.</td></tr>';
    repositoriesBody.querySelectorAll('[data-delete-repository]').forEach(button => button.addEventListener('click', async () => {
      if (!window.confirm(`Permanently delete ${button.dataset.name}?`)) return;
      try { await request(`/api/v1/admin/repositories/${button.dataset.deleteRepository}`, { method: 'DELETE' }); toast('Repository deleted'); await Promise.all([loadRepositories(), loadOverview(), loadAudit()]); }
      catch (error) { toast(error.message, true); }
    }));
  }

  function renderAudit(rows) {
    audit.innerHTML = rows.length ? rows.map(row => `<article class="admin-audit-item"><strong>${escapeHtml(row.action)}</strong> · ${escapeHtml(row.target_type)} ${escapeHtml(row.target_id)}<small>${escapeHtml(row.admin_name)} (${escapeHtml(row.admin_email)}) · ${formatDate(row.created_at)}${row.details ? ` · ${escapeHtml(row.details)}` : ''}</small></article>`).join('') : '<div class="admin-empty">No administrator activity yet.</div>';
  }

  const loadOverview = async () => renderMetrics(await request('/api/v1/admin/overview'));
  const loadUsers = async () => renderUsers(await request(`/api/v1/admin/users?search=${encodeURIComponent(search.value.trim())}`));
  const loadRepositories = async () => renderRepositories(await request('/api/v1/admin/repositories'));
  const loadAudit = async () => renderAudit(await request('/api/v1/admin/audit'));
  async function loadOwnerControl() {
    try {
      const [access, settings] = await Promise.all([request('/api/v1/core/access', { owner: true }), request('/api/v1/core/settings', { owner: true })]);
      if (settings === null) return renderOwnerControl({}, {}, [], null);
      const [model, services] = await Promise.all([request('/api/v1/core/model/diagnostics', { owner: true }), request('/api/v1/core/services', { owner: true })]);
      renderOwnerControl(access, model, services, settings);
    } catch (error) { renderRuntimeError(error); throw error; }
  }

  async function loadAll() {
    refresh.disabled = true;
    refresh.textContent = 'Refreshing…';
    const results = await Promise.allSettled([loadOverview(), loadUsers(), loadRepositories(), loadAudit(), loadOwnerControl()]);
    const failures = results.filter(result => result.status === 'rejected');
    if (failures.length) toast(`${failures.length} dashboard request${failures.length === 1 ? '' : 's'} failed`, true);
    lastUpdated.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
    refresh.disabled = false;
    refresh.textContent = 'Refresh';
  }

  let searchTimer;
  search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadUsers().catch(error => toast(error.message, true)), 250); });
  refresh.addEventListener('click', loadAll);
  loadAll();
})();
