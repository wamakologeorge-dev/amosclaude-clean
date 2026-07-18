(() => {
  const metrics = document.getElementById('admin-metrics');
  const usersBody = document.getElementById('admin-users-body');
  const repositoriesBody = document.getElementById('admin-repositories-body');
  const audit = document.getElementById('admin-audit');
  const search = document.getElementById('admin-user-search');
  const refresh = document.getElementById('admin-refresh');
  const health = document.getElementById('admin-health');

  const escapeHtml = value => String(value ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#039;');
  const formatBytes = bytes => {
    const value = Number(bytes || 0);
    if (value < 1024) return `${value} B`;
    if (value < 1048576) return `${(value / 1024).toFixed(1)} KB`;
    if (value < 1073741824) return `${(value / 1048576).toFixed(1)} MB`;
    return `${(value / 1073741824).toFixed(1)} GB`;
  };
  const formatDate = value => value ? new Date(value).toLocaleString() : '—';

  function toast(message, isError = false) {
    const container = document.getElementById('toast-container');
    const item = document.createElement('div');
    item.className = `admin-toast${isError ? ' error' : ''}`;
    item.textContent = message;
    container.appendChild(item);
    setTimeout(() => item.remove(), 4200);
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
      ...options,
    });
    if (response.status === 401) { window.location.href = '/login'; throw new Error('Not authenticated'); }
    if (response.status === 403) { window.location.href = '/'; throw new Error('Administrator access required'); }
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try { detail = (await response.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    if (response.status === 204) return null;
    return response.json();
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
    health.textContent = data.status === 'operational' ? '● Operational' : escapeHtml(data.status);
  }

  function renderUsers(users) {
    usersBody.innerHTML = users.length ? users.map(user => `
      <tr>
        <td><div class="admin-user"><strong>${escapeHtml(user.name)}</strong><small>${escapeHtml(user.email)}</small></div></td>
        <td>${escapeHtml(user.provider)}</td>
        <td>${Number(user.repository_count || 0)}</td>
        <td>${Number(user.session_count || 0)}</td>
        <td>${user.is_suspended ? '<span class="admin-badge warn">Suspended</span>' : '<span class="admin-badge ok">Active</span>'} ${user.is_admin ? '<span class="admin-badge admin">Admin</span>' : ''}</td>
        <td><div class="admin-actions">
          <button data-action="admin" data-id="${user.id}" data-value="${user.is_admin ? 'false' : 'true'}">${user.is_admin ? 'Remove admin' : 'Make admin'}</button>
          <button class="${user.is_suspended ? '' : 'danger'}" data-action="suspend" data-id="${user.id}" data-value="${user.is_suspended ? 'false' : 'true'}">${user.is_suspended ? 'Restore' : 'Suspend'}</button>
        </div></td>
      </tr>`).join('') : '<tr><td colspan="6">No users found.</td></tr>';

    usersBody.querySelectorAll('button[data-action]').forEach(button => button.addEventListener('click', async () => {
      const isAdminChange = button.dataset.action === 'admin';
      const value = button.dataset.value === 'true';
      const label = isAdminChange ? (value ? 'promote this user to administrator' : 'remove administrator access') : (value ? 'suspend this account' : 'restore this account');
      if (!window.confirm(`Are you sure you want to ${label}?`)) return;
      try {
        await api(`/api/v1/admin/users/${button.dataset.id}`, { method: 'PATCH', body: JSON.stringify(isAdminChange ? { is_admin: value } : { is_suspended: value }) });
        toast('User updated');
        await loadUsers();
        await loadOverview();
        await loadAudit();
      } catch (error) { toast(error.message, true); }
    }));
  }

  function renderRepositories(repositories) {
    repositoriesBody.innerHTML = repositories.length ? repositories.map(repo => `
      <tr>
        <td><strong>${escapeHtml(repo.name)}</strong><br><small>#${repo.id}</small></td>
        <td><div class="admin-user"><strong>${escapeHtml(repo.owner_name)}</strong><small>${escapeHtml(repo.owner_email)}</small></div></td>
        <td>${escapeHtml(repo.visibility)}</td>
        <td>${formatBytes(repo.storage_bytes)}</td>
        <td>${formatDate(repo.updated_at)}</td>
        <td><div class="admin-actions"><a href="/workspace/${repo.id}">Open</a><button class="danger" data-delete-repository="${repo.id}" data-name="${escapeHtml(repo.name)}">Delete</button></div></td>
      </tr>`).join('') : '<tr><td colspan="6">No repositories found.</td></tr>';

    repositoriesBody.querySelectorAll('[data-delete-repository]').forEach(button => button.addEventListener('click', async () => {
      if (!window.confirm(`Permanently delete ${button.dataset.name}? This cannot be undone.`)) return;
      try {
        await api(`/api/v1/admin/repositories/${button.dataset.deleteRepository}`, { method: 'DELETE' });
        toast('Repository deleted');
        await loadRepositories();
        await loadOverview();
        await loadAudit();
      } catch (error) { toast(error.message, true); }
    }));
  }

  function renderAudit(rows) {
    audit.innerHTML = rows.length ? rows.map(row => `<article class="admin-audit-item"><strong>${escapeHtml(row.action)}</strong> · ${escapeHtml(row.target_type)} ${escapeHtml(row.target_id)}<small>${escapeHtml(row.admin_name)} (${escapeHtml(row.admin_email)}) · ${formatDate(row.created_at)}${row.details ? ` · ${escapeHtml(row.details)}` : ''}</small></article>`).join('') : '<div class="admin-empty">No administrator activity yet.</div>';
  }

  async function loadOverview() { renderMetrics(await api('/api/v1/admin/overview')); }
  async function loadUsers() { renderUsers(await api(`/api/v1/admin/users?search=${encodeURIComponent(search.value.trim())}`)); }
  async function loadRepositories() { renderRepositories(await api('/api/v1/admin/repositories')); }
  async function loadAudit() { renderAudit(await api('/api/v1/admin/audit')); }

  async function loadAll() {
    refresh.disabled = true;
    try { await Promise.all([loadOverview(), loadUsers(), loadRepositories(), loadAudit()]); }
    catch (error) { toast(error.message, true); }
    finally { refresh.disabled = false; }
  }

  let searchTimer;
  search.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => loadUsers().catch(error => toast(error.message, true)), 250); });
  refresh.addEventListener('click', loadAll);
  loadAll();
})();
